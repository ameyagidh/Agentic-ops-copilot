import pytest

from ops_copilot.graph import build_graph, close_graph
from ops_copilot.schemas import IncidentRequest


@pytest.mark.asyncio
async def test_full_run_grounded_scenario(settings_factory):
    """payments-api deterministically hashes to the db_pool_exhaustion mock
    scenario (see tools/mock.py) — asserts the whole graph, including
    parallel evidence fan-out, produces a grounded, non-fabricated finding.
    """
    settings = settings_factory()
    graph = await build_graph(settings)
    try:
        result = await graph.ainvoke(
            {
                "incident": IncidentRequest(
                    ticket_text=("Payments API is timing out for ~6% of requests since the last deploy."),
                    service_name="payments-api",
                )
            },
            config={"configurable": {"thread_id": "grounded"}},
        )
    finally:
        await close_graph(graph)

    assert result["logs"] is not None
    assert result["metrics"] is not None
    assert result["context"] is not None
    finding = result["finding"]
    assert finding.insufficient_evidence is False
    assert finding.hypotheses
    assert set(finding.evidence_refs) <= {"logs", "metrics", "context", "runbooks"}


@pytest.mark.asyncio
async def test_full_run_insufficient_evidence_scenario(settings_factory):
    settings = settings_factory()
    graph = await build_graph(settings)
    try:
        result = await graph.ainvoke(
            {
                "incident": IncidentRequest(
                    ticket_text="A user reported something odd about checkout-api once.",
                    service_name="checkout-api",
                )
            },
            config={"configurable": {"thread_id": "insufficient"}},
        )
    finally:
        await close_graph(graph)

    assert result["finding"].insufficient_evidence is True
    assert result["finding"].evidence_refs == []


@pytest.mark.asyncio
async def test_billing_category_skips_logs_and_metrics(settings_factory):
    """The router should skip log/metric collection for a billing incident
    — this is the "router agent" behavior the docs promise."""
    settings = settings_factory()
    graph = await build_graph(settings)
    try:
        result = await graph.ainvoke(
            {
                "incident": IncidentRequest(
                    ticket_text="Customer was charged twice for the same invoice.",
                    service_name="billing-service",
                )
            },
            config={"configurable": {"thread_id": "billing"}},
        )
    finally:
        await close_graph(graph)

    assert result["triage"].category == "billing"
    assert result.get("logs") is None
    assert result.get("metrics") is None
    assert result.get("context") is not None


@pytest.mark.asyncio
async def test_parallel_fanout_returns_disjoint_deltas_without_error(settings_factory):
    """Regression test for the InvalidUpdateError trap: fetch nodes must
    return only their own key, never the full state, or LangGraph raises
    when concurrent branches race to write the same keys.
    """
    settings = settings_factory()
    graph = await build_graph(settings)
    try:
        result = await graph.ainvoke(
            {
                "incident": IncidentRequest(
                    ticket_text="Latency spike on checkout-api after deploy.",
                    service_name="checkout-api",
                )
            },
            config={"configurable": {"thread_id": "fanout"}},
        )
    finally:
        await close_graph(graph)

    assert result["logs"] is not None
    assert result["metrics"] is not None
    assert result["context"] is not None
