"""FastAPI service: REST + SSE streaming API, plus the embedded static SPA.

Endpoints
---------
POST /api/v1/incidents            run an incident analysis, return the final RunRecord (JSON)
POST /api/v1/incidents/stream      same, but streamed as Server-Sent Events (live node progress)
GET  /api/v1/incidents             list recent runs (history)
GET  /api/v1/incidents/{run_id}    fetch one run
GET  /healthz                      liveness probe
GET  /readyz                       readiness probe (checks the model + backends resolve)
GET  /metrics                      Prometheus metrics
/                                   the dashboard SPA (static files)
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sse_starlette.sse import EventSourceResponse
from starlette.responses import Response

from ops_copilot.config import Settings, get_settings
from ops_copilot.graph import build_graph, close_graph
from ops_copilot.observability import (
    REQUEST_DURATION,
    REQUESTS_TOTAL,
    configure_logging,
    get_logger,
    new_request_id,
)
from ops_copilot.schemas import IncidentRequest, RunRecord
from ops_copilot.store import RunStore

logger = get_logger(__name__)

_WEB_DIR = Path(__file__).parent / "web"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_run_record(incident: IncidentRequest) -> RunRecord:
    now = _now()
    return RunRecord(
        run_id=uuid.uuid4().hex,
        status="pending",
        incident=incident,
        created_at=now,
        updated_at=now,
    )


async def _require_api_key(request: Request, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="missing or invalid API key")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.graph = await build_graph(settings)
        app.state.run_store = RunStore(settings.checkpoint_db_path.replace(".sqlite", "_runs.sqlite"))
        await app.state.run_store.open()
        logger.info("startup_complete", provider=settings.llm_provider)
        try:
            yield
        finally:
            await close_graph(app.state.graph)
            await app.state.run_store.close()

    app = FastAPI(
        title="Agentic Ops Copilot",
        description="An agentic AI copilot that triages incidents and drafts evidence-grounded root-cause hypotheses.",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        new_request_id()
        response = await call_next(request)
        return response

    async def _run_incident(app: FastAPI, incident: IncidentRequest) -> RunRecord:
        record = _new_run_record(incident)
        record.status = "running"
        start = time.perf_counter()
        try:
            result = await app.state.graph.ainvoke(
                {"incident": incident},
                config={"configurable": {"thread_id": record.run_id}},
            )
            record.triage = result.get("triage")
            record.logs = result.get("logs")
            record.metrics = result.get("metrics")
            record.context = result.get("context")
            record.runbooks = result.get("runbooks", [])
            record.finding = result.get("finding")
            record.status = "completed"
            REQUESTS_TOTAL.labels(status="completed").inc()
        except Exception as exc:  # noqa: BLE001 - guardrail: never crash the API on a bad run
            logger.error("incident_run_failed", error=str(exc))
            record.status = "failed"
            record.error = str(exc)
            REQUESTS_TOTAL.labels(status="failed").inc()
        finally:
            record.updated_at = _now()
            REQUEST_DURATION.observe(time.perf_counter() - start)
        await app.state.run_store.save(record)
        return record

    @app.post("/api/v1/incidents", response_model=RunRecord, dependencies=[Depends(_require_api_key)])
    async def create_incident(incident: IncidentRequest, request: Request) -> RunRecord:
        return await _run_incident(request.app, incident)

    @app.post("/api/v1/incidents/stream", dependencies=[Depends(_require_api_key)])
    async def create_incident_stream(incident: IncidentRequest, request: Request):
        app_ref = request.app

        async def event_generator():
            record = _new_run_record(incident)
            record.status = "running"
            yield {"event": "started", "data": json.dumps({"run_id": record.run_id})}
            start = time.perf_counter()
            try:
                async for chunk in app_ref.state.graph.astream(
                    {"incident": incident},
                    config={"configurable": {"thread_id": record.run_id}},
                    stream_mode="updates",
                ):
                    for node_name, delta in chunk.items():
                        yield {
                            "event": "node",
                            "data": json.dumps({"node": node_name, "keys": list(delta.keys())}),
                        }
                        for key in ("triage", "logs", "metrics", "context", "runbooks", "finding"):
                            if key in delta:
                                setattr(record, key, delta[key])
                record.status = "completed"
                REQUESTS_TOTAL.labels(status="completed").inc()
            except Exception as exc:  # noqa: BLE001
                logger.error("incident_stream_failed", error=str(exc))
                record.status = "failed"
                record.error = str(exc)
                REQUESTS_TOTAL.labels(status="failed").inc()
            finally:
                record.updated_at = _now()
                REQUEST_DURATION.observe(time.perf_counter() - start)
            await app_ref.state.run_store.save(record)
            yield {"event": "completed", "data": record.model_dump_json()}

        return EventSourceResponse(event_generator())

    @app.get("/api/v1/incidents", response_model=list[RunRecord], dependencies=[Depends(_require_api_key)])
    async def list_incidents(request: Request, limit: int = 50) -> list[RunRecord]:
        return await request.app.state.run_store.list_recent(limit=limit)

    @app.get("/api/v1/incidents/{run_id}", response_model=RunRecord, dependencies=[Depends(_require_api_key)])
    async def get_incident(run_id: str, request: Request) -> RunRecord:
        record = await request.app.state.run_store.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="run not found")
        return record

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(request: Request) -> dict:
        return {
            "status": "ready",
            "llm_provider": request.app.state.settings.llm_provider,
            "logs_backend": request.app.state.settings.logs_backend,
            "metrics_backend": request.app.state.settings.metrics_backend,
        }

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", path=str(request.url), error=str(exc))
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    if _WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")

    return app


app = create_app()
