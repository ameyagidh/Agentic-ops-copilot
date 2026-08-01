"""Persistence for run records shown by the history endpoint / UI.

Deliberately separate from the LangGraph checkpointer (``graph.py``), which
persists step-by-step execution state for resumability. This store persists
the API-facing summary (``RunRecord``) that the UI lists and polls — a
plain SQLite table is simpler to query than reconstructing it from
checkpoints, and keeps the two concerns decoupled.
"""

from __future__ import annotations

import json

import aiosqlite

from ops_copilot.schemas import RunRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class RunStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def save(self, record: RunRecord) -> None:
        assert self._conn is not None, "RunStore.open() must be called first"
        await self._conn.execute(
            "INSERT INTO runs (run_id, created_at, payload) VALUES (?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET payload = excluded.payload",
            (record.run_id, record.created_at, record.model_dump_json()),
        )
        await self._conn.commit()

    async def get(self, run_id: str) -> RunRecord | None:
        assert self._conn is not None, "RunStore.open() must be called first"
        cursor = await self._conn.execute("SELECT payload FROM runs WHERE run_id = ?", (run_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return RunRecord.model_validate(json.loads(row[0]))

    async def list_recent(self, limit: int = 50) -> list[RunRecord]:
        assert self._conn is not None, "RunStore.open() must be called first"
        cursor = await self._conn.execute("SELECT payload FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = await cursor.fetchall()
        return [RunRecord.model_validate(json.loads(row[0])) for row in rows]
