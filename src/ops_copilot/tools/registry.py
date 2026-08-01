"""Resolves configured backend names to concrete adapter instances."""

from __future__ import annotations

from ops_copilot.config import Settings
from ops_copilot.tools.base import LogsBackend, MetricsBackend, ServiceCatalog
from ops_copilot.tools.loki import LokiLogsBackend
from ops_copilot.tools.mock import MockLogsBackend, MockMetricsBackend, MockServiceCatalog
from ops_copilot.tools.prometheus import PrometheusMetricsBackend


def get_logs_backend(settings: Settings) -> LogsBackend:
    if settings.logs_backend == "loki":
        return LokiLogsBackend(settings.loki_base_url, settings.backend_timeout_seconds)
    return MockLogsBackend()


def get_metrics_backend(settings: Settings) -> MetricsBackend:
    if settings.metrics_backend == "prometheus":
        return PrometheusMetricsBackend(settings.prometheus_base_url, settings.backend_timeout_seconds)
    return MockMetricsBackend()


def get_service_catalog(settings: Settings) -> ServiceCatalog:
    # No real service-catalog adapter ships out of the box; implement the
    # ServiceCatalog protocol against your CMDB/internal service registry
    # and register it here.
    return MockServiceCatalog()
