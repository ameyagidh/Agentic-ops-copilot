"""The copilot's LangGraph state machine.

    incident -> route --(conditional fan-out)--> [fetch_logs | fetch_metrics | fetch_context]
                                                          |
                                                          v
                                              retrieve_runbooks -> synthesize -> validate -> END

``route`` is the router agent: it classifies severity/category and decides
*which* evidence sources are actually relevant (e.g. a pure billing question
skips log/metrics collection). The three ``fetch_*`` nodes run truly in
parallel — LangGraph invokes all active branches of a conditional fan-out
concurrently. Each fetch node returns **only its own state key** (e.g.
``{"logs": ...}``), never the whole state dict: returning full state from
concurrent branches raises ``InvalidUpdateError`` because two branches would
race to overwrite the same keys.
"""

from __future__ import annotations

import operator
from pathlib import Path
from typing import Annotated, Any, TypedDict
from weakref import WeakKeyDictionary

from langgraph.graph import END, StateGraph

from ops_copilot.config import Settings, get_settings
from ops_copilot.guardrails import validate_finding
from ops_copilot.llm import get_chat_model
from ops_copilot.observability import get_logger
from ops_copilot.retrieval import get_runbook_store
from ops_copilot.schemas import (
    Category,
    Finding,
    IncidentRequest,
    LogEvidence,
    MetricEvidence,
    RunbookExcerpt,
    ServiceContext,
    Severity,
    Triage,
)
from ops_copilot.tools.base import BackendError
from ops_copilot.tools.registry import get_logs_backend, get_metrics_backend, get_service_catalog

logger = get_logger(__name__)

# Categories where log/metric evidence is unlikely to be useful — the router
# skips those branches entirely rather than fetching evidence nobody needs.
_NO_LOG_METRIC_CATEGORIES = {"billing", "auth"}


class OpsState(TypedDict, total=False):
    incident: IncidentRequest
    triage: Triage
    need_logs: bool
    need_metrics: bool
    need_context: bool
    logs: LogEvidence | None
    metrics: MetricEvidence | None
    context: ServiceContext | None
    runbooks: list[RunbookExcerpt]
    finding: Finding
    retry_count: int
    # Sources that were *attempted* but failed with a BackendError (real
    # backend down/timeout), as distinct from sources the router decided not
    # to collect at all. Multiple fetch_* nodes can append to this
    # concurrently, so — unlike the other keys above — it needs a reducer
    # rather than a disjoint per-node key.
    degraded: Annotated[list[str], operator.add]


def _triage_ticket(ticket_text: str) -> Triage:
    """Lightweight rules-based classifier. In production this would call an
    internal classifier/ML model; kept deterministic here so the router's
    decisions are reproducible without an LLM call.
    """
    text = ticket_text.lower()
    severity: Severity
    if any(w in text for w in ("down", "outage", "unavailable", "cannot log in", "can't log in")):
        severity = "SEV1"
    elif any(w in text for w in ("timing out", "timeout", "elevated", "spike", "degraded")):
        severity = "SEV2"
    elif any(w in text for w in ("slow", "intermittent")):
        severity = "SEV3"
    else:
        severity = "SEV4"

    category: Category
    if any(w in text for w in ("charge", "invoice", "billing", "refund", "payment failed")):
        category = "billing"
    elif any(w in text for w in ("login", "auth", "password", "token", "unauthorized")):
        category = "auth"
    elif any(w in text for w in ("deploy", "release", "rollout")):
        category = "deployment"
    elif any(w in text for w in ("timeout", "latency", "slow")):
        category = "latency"
    elif any(w in text for w in ("error", "5xx", "exception", "fail")):
        category = "errors"
    else:
        category = "unknown"

    return Triage(severity=severity, category=category, rationale=f"keyword-matched from ticket text ({category})")


async def route_node(state: OpsState) -> dict[str, Any]:
    incident = state["incident"]
    triage = _triage_ticket(incident.ticket_text)
    needs_logs_metrics = triage.category not in _NO_LOG_METRIC_CATEGORIES
    return {
        "triage": triage,
        "need_logs": needs_logs_metrics,
        "need_metrics": needs_logs_metrics,
        "need_context": True,  # ownership/deploy context is always useful
    }


def _route_condition(state: OpsState) -> list[str]:
    dests = []
    if state.get("need_logs"):
        dests.append("fetch_logs")
    if state.get("need_metrics"):
        dests.append("fetch_metrics")
    if state.get("need_context"):
        dests.append("fetch_context")
    return dests or ["retrieve_runbooks"]


async def fetch_logs_node(state: OpsState, settings: Settings) -> dict[str, Any]:
    backend = get_logs_backend(settings)
    service_name = state["incident"].service_name
    try:
        logs = await backend.summarize(service_name, window_minutes=30)
    except BackendError as exc:
        logger.error("logs_backend_unavailable", service_name=service_name, error=str(exc))
        return {"logs": None, "degraded": ["logs"]}
    return {"logs": logs}


async def fetch_metrics_node(state: OpsState, settings: Settings) -> dict[str, Any]:
    backend = get_metrics_backend(settings)
    service_name = state["incident"].service_name
    try:
        metrics = await backend.query(service_name)
    except BackendError as exc:
        logger.error("metrics_backend_unavailable", service_name=service_name, error=str(exc))
        return {"metrics": None, "degraded": ["metrics"]}
    return {"metrics": metrics}


async def fetch_context_node(state: OpsState, settings: Settings) -> dict[str, Any]:
    catalog = get_service_catalog(settings)
    service_name = state["incident"].service_name
    try:
        context = await catalog.lookup(service_name)
    except BackendError as exc:
        logger.error("service_catalog_unavailable", service_name=service_name, error=str(exc))
        return {"context": None, "degraded": ["context"]}
    return {"context": context}


async def retrieve_runbooks_node(state: OpsState, settings: Settings) -> dict[str, Any]:
    store = get_runbook_store(settings)
    query = f"{state['triage'].category} {state['incident'].ticket_text}"
    runbooks = await store.retrieve(query, k=3)
    return {"runbooks": runbooks}


def _unavailable_reason(key: str, state: OpsState) -> str:
    """Distinguishes "the router decided this wasn't relevant" from "we
    tried to fetch it and the backend failed" — an on-call engineer needs to
    know which one happened, and the model must not treat a backend outage
    as a clean absence of evidence.
    """
    if key in (state.get("degraded") or []):
        return "unavailable — backend error while fetching this evidence"
    return "none — not collected for this category"


def _format_evidence(state: OpsState) -> str:
    lines = []
    lines.append(f"Triage: severity={state['triage'].severity}, category={state['triage'].category}")
    logs = state.get("logs")
    lines.append(f"Logs: {logs.summary if logs else _unavailable_reason('logs', state)}")
    metrics = state.get("metrics")
    if metrics:
        lines.append(
            "Metrics: p99 latency "
            f"{metrics.p99_latency_ms:.0f}ms (baseline {metrics.baseline_latency_ms:.0f}ms), "
            f"error rate {metrics.error_rate_pct:.1f}%, throughput {metrics.throughput_rps:.0f} rps"
        )
    else:
        lines.append(f"Metrics: {_unavailable_reason('metrics', state)}")
    context = state.get("context")
    if context:
        lines.append(
            f"Service context: owned by {context.owner_team}; depends on {', '.join(context.dependencies) or 'none'}; "
            f"{context.recent_change_summary or 'no recent deploy on record'}"
        )
    else:
        lines.append(f"Service context: {_unavailable_reason('context', state)}")
    runbooks = state.get("runbooks") or []
    if runbooks:
        lines.append("Runbooks:")
        for r in runbooks:
            lines.append(f"  - {r.title}: {r.snippet}")
    else:
        lines.append("Runbooks: none retrieved")
    return "\n".join(lines)


async def synthesize_node(state: OpsState, settings: Settings) -> dict[str, Any]:
    """Ground the finding strictly in retrieved evidence via structured
    output — the model must return a ``Finding``, not free text, so
    downstream validation can check its claims mechanically.
    """
    evidence_text = _format_evidence(state)
    prompt = (
        "You are an SRE copilot. Using ONLY the evidence below, propose a root-cause "
        "hypothesis and a recommended next action. Populate evidence_refs with only the "
        "evidence categories (logs, metrics, context, runbooks) that actually support your "
        "hypothesis. If the evidence doesn't support a clear root cause, set "
        "insufficient_evidence=true instead of speculating.\n\n" + evidence_text
    )
    model = get_chat_model(settings)
    structured = model.with_structured_output(Finding)
    finding = await structured.ainvoke(prompt)
    return {"finding": finding}


async def validate_node(state: OpsState) -> dict[str, Any]:
    collected = {k for k in ("logs", "metrics", "context", "runbooks") if state.get(k)}
    finding = validate_finding(state["finding"], collected)
    return {"finding": finding}


async def build_graph(settings: Settings | None = None):
    """Compiles the copilot graph with a SQLite checkpointer so runs are
    resumable and inspectable across process restarts (required for the
    API's run-history endpoint to survive a redeploy).

    Async because ``AsyncSqliteSaver`` owns a live ``aiosqlite`` connection
    that must be opened on the running event loop. Call ``close_graph`` with
    the returned handle during shutdown to release it cleanly.
    """
    settings = settings or get_settings()
    graph = StateGraph(OpsState)

    async def _fetch_logs(state: OpsState) -> dict[str, Any]:
        return await fetch_logs_node(state, settings)

    async def _fetch_metrics(state: OpsState) -> dict[str, Any]:
        return await fetch_metrics_node(state, settings)

    async def _fetch_context(state: OpsState) -> dict[str, Any]:
        return await fetch_context_node(state, settings)

    async def _retrieve_runbooks(state: OpsState) -> dict[str, Any]:
        return await retrieve_runbooks_node(state, settings)

    async def _synthesize(state: OpsState) -> dict[str, Any]:
        return await synthesize_node(state, settings)

    graph.add_node("route", route_node)
    graph.add_node("fetch_logs", _fetch_logs)
    graph.add_node("fetch_metrics", _fetch_metrics)
    graph.add_node("fetch_context", _fetch_context)
    graph.add_node("retrieve_runbooks", _retrieve_runbooks)
    graph.add_node("synthesize", _synthesize)
    graph.add_node("validate", validate_node)

    graph.set_entry_point("route")
    graph.add_conditional_edges(
        "route",
        _route_condition,  # type: ignore[arg-type]  # LangGraph's Hashable bound doesn't cover list[str] cleanly
        ["fetch_logs", "fetch_metrics", "fetch_context", "retrieve_runbooks"],
    )
    graph.add_edge("fetch_logs", "retrieve_runbooks")
    graph.add_edge("fetch_metrics", "retrieve_runbooks")
    graph.add_edge("fetch_context", "retrieve_runbooks")
    graph.add_edge("retrieve_runbooks", "synthesize")
    graph.add_edge("synthesize", "validate")
    graph.add_edge("validate", END)

    checkpointer, conn = await _build_checkpointer(settings)
    compiled = graph.compile(checkpointer=checkpointer)
    _connections[compiled] = conn  # closed by close_graph()
    return compiled


# Weak-keyed so a compiled graph's connection is tracked without a dynamic
# attribute on the (third-party) CompiledStateGraph object, and without
# keeping the graph alive past its own lifetime.
_connections: WeakKeyDictionary = WeakKeyDictionary()


async def close_graph(compiled_graph: Any) -> None:
    """Releases the checkpointer's SQLite connection. Call during app
    shutdown (see ``api.py``'s lifespan handler).
    """
    conn = _connections.pop(compiled_graph, None)
    if conn is not None:
        await conn.close()


async def _build_checkpointer(settings: Settings):
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    db_path = Path(settings.checkpoint_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(db_path))
    # WAL mode lets readers and the single writer coexist without
    # "database is locked" errors under concurrent access (e.g. multiple
    # uvicorn workers, or a run overlapping with a history read).
    await conn.execute("PRAGMA journal_mode=WAL;")
    return AsyncSqliteSaver(conn), conn
