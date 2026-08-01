"""Real metrics adapter: queries a Prometheus (or compatible) HTTP API.

Reference implementation showing how to wire a real backend behind the
``MetricsBackend`` protocol. Swap the PromQL queries for whatever your
service naming/labels look like.
"""

from __future__ import annotations

import httpx

from ops_copilot.schemas import MetricEvidence
from ops_copilot.tools.base import BackendError


class PrometheusMetricsBackend:
    def __init__(self, base_url: str, timeout_seconds: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def query(self, service_name: str) -> MetricEvidence:
        bucket = f'http_request_duration_ms_bucket{{service="{service_name}"}}'
        requests_total = f'http_requests_total{{service="{service_name}"}}'
        requests_5xx = f'http_requests_total{{service="{service_name}",status=~"5.."}}'
        queries = {
            "p99_latency_ms": f"histogram_quantile(0.99, rate({bucket}[5m]))",
            "baseline_latency_ms": f"histogram_quantile(0.50, rate({bucket}[1h] offset 1d))",
            "error_rate_pct": (f"100 * sum(rate({requests_5xx}[5m])) / sum(rate({requests_total}[5m]))"),
            "throughput_rps": f"sum(rate({requests_total}[5m]))",
        }
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
                values: dict[str, float] = {}
                for field, promql in queries.items():
                    resp = await client.get("/api/v1/query", params={"query": promql})
                    resp.raise_for_status()
                    payload = resp.json()
                    result = payload.get("data", {}).get("result", [])
                    values[field] = float(result[0]["value"][1]) if result else 0.0
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            raise BackendError(f"Prometheus query failed for {service_name}: {exc}") from exc

        return MetricEvidence(service_name=service_name, **values)
