import json

import httpx
import pytest
from asgi_lifespan import LifespanManager

from ops_copilot.api import create_app


@pytest.fixture
async def client(settings_factory):
    settings = settings_factory()
    app = create_app(settings)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz(client):
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["llm_provider"] == "fake"


@pytest.mark.asyncio
async def test_metrics_endpoint(client):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert b"ops_copilot" in resp.content


@pytest.mark.asyncio
async def test_create_incident_and_fetch_it(client):
    resp = await client.post(
        "/api/v1/incidents",
        json={
            "ticket_text": "Payments API is timing out for ~6% of requests since the last deploy.",
            "service_name": "payments-api",
        },
    )
    assert resp.status_code == 200
    record = resp.json()
    assert record["status"] == "completed"
    assert record["finding"] is not None

    fetched = await client.get(f"/api/v1/incidents/{record['run_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["run_id"] == record["run_id"]


@pytest.mark.asyncio
async def test_unknown_run_id_is_404(client):
    resp = await client.get("/api/v1/incidents/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_incidents_history(client):
    await client.post(
        "/api/v1/incidents",
        json={"ticket_text": "checkout is slow", "service_name": "checkout-api"},
    )
    resp = await client.get("/api/v1/incidents")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) >= 1


@pytest.mark.asyncio
async def test_invalid_payload_is_422(client):
    resp = await client.post("/api/v1/incidents", json={"service_name": "checkout-api"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_stream_endpoint_emits_node_and_completed_events(client):
    async with client.stream(
        "POST",
        "/api/v1/incidents/stream",
        json={
            "ticket_text": "Payments API is timing out for ~6% of requests since the last deploy.",
            "service_name": "payments-api",
        },
    ) as resp:
        assert resp.status_code == 200
        event_names = []
        completed_payload = None
        buffer = ""
        async for chunk in resp.aiter_text():
            buffer += chunk
        buffer = buffer.replace("\r\n", "\n")
        for raw in buffer.split("\n\n"):
            if not raw.strip():
                continue
            event_name = None
            data = None
            for line in raw.splitlines():
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                if line.startswith("data:"):
                    data = line.split(":", 1)[1].strip()
            if event_name:
                event_names.append(event_name)
            if event_name == "completed" and data:
                completed_payload = json.loads(data)

    assert "started" in event_names
    assert "node" in event_names
    assert "completed" in event_names
    assert completed_payload is not None
    assert completed_payload["status"] == "completed"


@pytest.mark.asyncio
async def test_rate_limit_returns_429_once_exceeded(settings_factory):
    settings = settings_factory(rate_limit_per_minute=2)
    app = create_app(settings)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            first = await c.get("/api/v1/incidents")
            second = await c.get("/api/v1/incidents")
            third = await c.get("/api/v1/incidents")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers["retry-after"] == "60"


@pytest.mark.asyncio
async def test_rate_limit_exempts_health_probes(settings_factory):
    settings = settings_factory(rate_limit_per_minute=1)
    app = create_app(settings)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            for _ in range(5):
                resp = await c.get("/healthz")
                assert resp.status_code == 200


@pytest.mark.asyncio
async def test_auth_required_when_api_key_configured(settings_factory):
    settings = settings_factory(api_key="topsecret")
    app = create_app(settings)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            unauthorized = await c.get("/api/v1/incidents")
            assert unauthorized.status_code == 401

            authorized = await c.get("/api/v1/incidents", headers={"X-API-Key": "topsecret"})
            assert authorized.status_code == 200
