"""Deterministic mock backends.

Scenarios are selected by a hash of ``service_name`` so the same service
always produces the same evidence — reproducible demos and reproducible
tests, with zero setup. This is the default backend for every capability.
"""

from __future__ import annotations

import hashlib

from ops_copilot.schemas import LogEvidence, MetricEvidence, ServiceContext

_SCENARIOS = [
    {
        "name": "db_pool_exhaustion",
        "log_summary": "elevated 5xx rate; repeated 'connection pool exhausted' errors against the primary database",
        "error_signatures": ["ConnectionPoolTimeoutError", "5xx spike"],
        "p99_latency_ms": 4200.0,
        "baseline_latency_ms": 800.0,
        "error_rate_pct": 6.1,
        "throughput_rps": 340.0,
        "recent_change_summary": "deployed 40 minutes ago",
        "last_deploy_minutes_ago": 40,
    },
    {
        "name": "bad_deploy",
        "log_summary": "error rate jumped immediately after the latest release; stack traces point to a null "
        "dereference in the new payment-validation path",
        "error_signatures": ["NullPointerException", "5xx spike post-deploy"],
        "p99_latency_ms": 1500.0,
        "baseline_latency_ms": 900.0,
        "error_rate_pct": 9.8,
        "throughput_rps": 210.0,
        "recent_change_summary": "deployed 12 minutes ago",
        "last_deploy_minutes_ago": 12,
    },
    {
        "name": "dependency_outage",
        "log_summary": "timeouts calling a downstream dependency; no errors originate from this service's own code",
        "error_signatures": ["UpstreamTimeoutError"],
        "p99_latency_ms": 6100.0,
        "baseline_latency_ms": 750.0,
        "error_rate_pct": 4.4,
        "throughput_rps": 300.0,
        "recent_change_summary": None,
        "last_deploy_minutes_ago": None,
    },
    {
        "name": "insufficient_evidence",
        "log_summary": "logs are within normal bounds; no notable error patterns",
        "error_signatures": [],
        "p99_latency_ms": 820.0,
        "baseline_latency_ms": 800.0,
        "error_rate_pct": 0.3,
        "throughput_rps": 500.0,
        "recent_change_summary": None,
        "last_deploy_minutes_ago": None,
    },
]

_OWNERS = ["fees-platform", "checkout-platform", "identity", "growth", "platform-infra"]
_DEPS = ["billing-db", "auth-service", "inventory-api", "notifications", "payments-gateway"]


def _scenario_for(service_name: str) -> dict:
    digest = hashlib.sha256(service_name.encode("utf-8")).hexdigest()
    idx = int(digest, 16) % len(_SCENARIOS)
    return _SCENARIOS[idx]


def _pick(service_name: str, options: list[str], salt: str) -> str:
    digest = hashlib.sha256(f"{service_name}:{salt}".encode()).hexdigest()
    return options[int(digest, 16) % len(options)]


class MockLogsBackend:
    async def summarize(self, service_name: str, window_minutes: int) -> LogEvidence:
        scenario = _scenario_for(service_name)
        return LogEvidence(
            service_name=service_name,
            window_minutes=window_minutes,
            summary=f"[log summary for {service_name}, last {window_minutes}m]: {scenario['log_summary']}",
            error_signatures=list(scenario["error_signatures"]),
        )


class MockMetricsBackend:
    async def query(self, service_name: str) -> MetricEvidence:
        scenario = _scenario_for(service_name)
        return MetricEvidence(
            service_name=service_name,
            p99_latency_ms=scenario["p99_latency_ms"],
            baseline_latency_ms=scenario["baseline_latency_ms"],
            error_rate_pct=scenario["error_rate_pct"],
            throughput_rps=scenario["throughput_rps"],
        )


class MockServiceCatalog:
    async def lookup(self, service_name: str) -> ServiceContext:
        scenario = _scenario_for(service_name)
        owner = _pick(service_name, _OWNERS, "owner")
        num_deps = 1 + (hash(service_name) % 3)
        deps = [_pick(service_name, _DEPS, f"dep{i}") for i in range(num_deps)]
        return ServiceContext(
            service_name=service_name,
            owner_team=owner,
            dependencies=sorted(set(deps)),
            last_deploy_minutes_ago=scenario["last_deploy_minutes_ago"],
            recent_change_summary=scenario["recent_change_summary"],
        )
