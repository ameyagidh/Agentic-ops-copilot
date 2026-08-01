"""Structured logging and Prometheus metrics."""

from __future__ import annotations

import logging
import sys
import time
import uuid
from contextvars import ContextVar

import structlog
from prometheus_client import Counter, Histogram

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

REQUESTS_TOTAL = Counter("ops_copilot_requests_total", "Total incident analysis requests", ["status"])
REQUEST_DURATION = Histogram("ops_copilot_request_duration_seconds", "Time to analyze one incident")
NODE_DURATION = Histogram("ops_copilot_node_duration_seconds", "Time spent in each graph node", ["node"])


def _add_request_id(logger, method_name, event_dict):
    event_dict["request_id"] = request_id_var.get()
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_request_id,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(log_level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    return structlog.get_logger(name)


def new_request_id() -> str:
    rid = uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    return rid


class timed_node:
    """Context manager that records node latency into ``NODE_DURATION``."""

    def __init__(self, node_name: str) -> None:
        self._node = node_name
        self._start = 0.0

    def __enter__(self) -> timed_node:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> None:
        NODE_DURATION.labels(node=self._node).observe(time.perf_counter() - self._start)
