"""Read-only access to the `pr_trace` table.

The agents service writes traces; the dashboard reads them. We keep the
queries narrow (just what the UI renders) so the dashboard doesn't drift
into business logic.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from ingress.logging import get_logger

log = get_logger("ingress.dashboard.traces")


_LIST_SQL = """
SELECT
    task_id,
    event_id,
    workflow,
    source_channel,
    summary_markdown,
    cto_output ->> 'decision'   AS decision,
    cto_output ->> 'confidence' AS confidence,
    completed_at,
    created_at
FROM pr_trace
ORDER BY created_at DESC
LIMIT %s OFFSET %s
"""

_DETAIL_SQL = """
SELECT
    task_id, event_id, workflow, source_channel,
    pr_metadata, dispatcher_output, specialist_outputs,
    lead_outputs, cto_output, risk_metadata,
    summary_markdown, detail_markdown, human_decision,
    created_at, completed_at
FROM pr_trace
WHERE task_id = %s
"""


class TraceReader:
    """Async reader over `pr_trace`.

    Re-uses a single connection. Cheap for the dashboard's QPS; revisit
    if usage grows.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn: psycopg.AsyncConnection | None = None

    async def connect(self) -> None:
        self._conn = await psycopg.AsyncConnection.connect(
            self._dsn, row_factory=dict_row
        )
        log.info("dashboard.trace_reader.connected")

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def list_recent(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        assert self._conn is not None, "TraceReader not connected"
        async with self._conn.cursor() as cur:
            await cur.execute(_LIST_SQL, (limit, offset))
            rows = await cur.fetchall()
        return rows

    async def get(self, task_id: str) -> dict[str, Any] | None:
        assert self._conn is not None, "TraceReader not connected"
        async with self._conn.cursor() as cur:
            await cur.execute(_DETAIL_SQL, (task_id,))
            return await cur.fetchone()
