"""Adapter protocols for the ops systems each tool wraps.

Any company can drop in their own implementation of these protocols (point
them at Datadog, Splunk, PagerDuty, an internal service catalog, ...) without
touching the graph or API. Two implementations ship out of the box:

- ``mock``: rich, deterministic, zero-setup — the default.
- one real adapter per capability (``prometheus`` for metrics, ``loki`` for
  logs) as a concrete example of wiring a real backend.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ops_copilot.schemas import LogEvidence, MetricEvidence, ServiceContext


@runtime_checkable
class LogsBackend(Protocol):
    async def summarize(self, service_name: str, window_minutes: int) -> LogEvidence: ...


@runtime_checkable
class MetricsBackend(Protocol):
    async def query(self, service_name: str) -> MetricEvidence: ...


@runtime_checkable
class ServiceCatalog(Protocol):
    async def lookup(self, service_name: str) -> ServiceContext: ...


class BackendError(RuntimeError):
    """Raised by real adapters on network/auth/timeout failures so the graph
    can degrade gracefully instead of crashing a run.
    """
