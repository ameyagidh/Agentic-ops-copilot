"""Real adapters (Prometheus, Loki) tested against httpx.MockTransport —
no real network access, but exercises the actual HTTP call/parse logic.
"""

import httpx
import pytest

from ops_copilot.tools.base import BackendError
from ops_copilot.tools.loki import LokiLogsBackend
from ops_copilot.tools.prometheus import PrometheusMetricsBackend


@pytest.mark.asyncio
async def test_prometheus_backend_parses_query_results(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = {"data": {"result": [{"value": [0, "123.4"]}]}}
        return httpx.Response(200, json=payload, request=request)

    backend = PrometheusMetricsBackend("http://prometheus.local")

    async def fake_get(self, url, params=None):
        return handler(httpx.Request("GET", url, params=params))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await backend.query("checkout-api")
    assert result.p99_latency_ms == 123.4
    assert result.service_name == "checkout-api"


@pytest.mark.asyncio
async def test_prometheus_backend_raises_backend_error_on_http_failure(monkeypatch):
    async def fake_get(self, url, params=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    backend = PrometheusMetricsBackend("http://prometheus.local")
    with pytest.raises(BackendError):
        await backend.query("checkout-api")


@pytest.mark.asyncio
async def test_loki_backend_parses_and_summarizes_lines(monkeypatch):
    payload = {
        "data": {
            "result": [
                {"values": [["0", "ConnectionPoolTimeoutError: pool exhausted"]]},
            ]
        }
    }

    async def fake_get(self, url, params=None):
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    backend = LokiLogsBackend("http://loki.local")
    result = await backend.summarize("checkout-api", window_minutes=15)
    assert "ConnectionPoolTimeoutError" in result.error_signatures
    assert result.window_minutes == 15


@pytest.mark.asyncio
async def test_loki_backend_raises_backend_error_on_http_failure(monkeypatch):
    async def fake_get(self, url, params=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    backend = LokiLogsBackend("http://loki.local")
    with pytest.raises(BackendError):
        await backend.summarize("checkout-api", window_minutes=15)
