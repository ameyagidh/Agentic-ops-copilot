"""Real logs adapter: queries Grafana Loki's HTTP API and summarizes the
result. Reference implementation for the ``LogsBackend`` protocol.
"""

from __future__ import annotations

import re

import httpx

from ops_copilot.schemas import LogEvidence
from ops_copilot.tools.base import BackendError

_ERROR_PATTERN = re.compile(r"\b([A-Z][a-zA-Z]*(?:Error|Exception|Timeout))\b")


class LokiLogsBackend:
    def __init__(self, base_url: str, timeout_seconds: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def summarize(self, service_name: str, window_minutes: int) -> LogEvidence:
        query = f'{{service="{service_name}"}} |~ "(?i)error|warn|exception"'
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
                resp = await client.get(
                    "/loki/api/v1/query_range",
                    params={"query": query, "limit": 200, "since": f"{window_minutes}m"},
                )
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise BackendError(f"Loki query failed for {service_name}: {exc}") from exc

        lines: list[str] = []
        for stream in payload.get("data", {}).get("result", []):
            for _, line in stream.get("values", []):
                lines.append(line)

        signatures = sorted({m.group(1) for line in lines for m in [_ERROR_PATTERN.search(line)] if m})

        if not lines:
            summary = f"[log summary for {service_name}, last {window_minutes}m]: no error/warn lines found"
        else:
            summary = (
                f"[log summary for {service_name}, last {window_minutes}m]: {len(lines)} error/warn lines; "
                f"top signatures: {', '.join(signatures[:5]) or 'none identified'}"
            )

        return LogEvidence(
            service_name=service_name,
            window_minutes=window_minutes,
            summary=summary,
            error_signatures=signatures,
        )
