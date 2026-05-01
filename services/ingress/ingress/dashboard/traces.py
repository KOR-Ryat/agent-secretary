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


# Range token → SQL interval. Whitelisted to avoid string interpolation
# of user input into the query. `all` means no time filter.
_RANGE_TO_INTERVAL: dict[str, str | None] = {
    "1h": "1 hour",
    "6h": "6 hours",
    "24h": "24 hours",
    "7d": "7 days",
    "30d": "30 days",
    "all": None,
}


_LIST_COLUMNS = """
    task_id,
    event_id,
    workflow,
    source_channel,
    summary_markdown,
    cto_output ->> 'decision'   AS decision,
    cto_output ->> 'confidence' AS confidence,
    completed_at,
    created_at
"""

# Whitelists: anything not in here gets rejected at the route boundary,
# never reaches SQL. Decision values match the `cto_output.decision`
# strings emitted by the CTO persona; "none" is the sentinel for
# rows where the CTO never wrote a decision.
_DECISIONS = {"auto-merge", "request-changes", "escalate-to-human", "none"}
_WORKFLOWS = {
    "pr_review",
    "pr_review_monolithic",
    "code_analyze",
    "code_modify",
    "linear_issue",
}


def _build_list_sql(
    *,
    decision: str | None,
    workflow: str | None,
    range_token: str | None,
) -> tuple[str, list[Any]]:
    """Compose the trace-list query + bind values from validated filters.

    Returns the SQL text and a parameter list. All filter values are
    validated against whitelists before this function — but we still
    bind them as %s parameters rather than f-string interpolation."""
    where_clauses: list[str] = []
    params: list[Any] = []

    if decision == "none":
        where_clauses.append("cto_output ->> 'decision' IS NULL")
    elif decision is not None:
        where_clauses.append("cto_output ->> 'decision' = %s")
        params.append(decision)

    if workflow is not None:
        where_clauses.append("workflow = %s")
        params.append(workflow)

    if range_token is not None and range_token != "all":
        interval = _RANGE_TO_INTERVAL[range_token]
        where_clauses.append("created_at >= NOW() - %s::interval")
        params.append(interval)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = (
        f"SELECT {_LIST_COLUMNS} FROM pr_trace {where_sql} "
        "ORDER BY created_at DESC LIMIT %s OFFSET %s"
    )
    return sql, params

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


def _decision_stats_sql(*, with_window: bool) -> str:
    where = "WHERE completed_at IS NOT NULL"
    if with_window:
        where += " AND completed_at >= NOW() - %s::interval"
    return f"""
SELECT
    COUNT(*)::int                                                          AS total,
    COUNT(*) FILTER (WHERE cto_output ->> 'decision' = 'auto-merge')::int  AS auto_merge,
    COUNT(*) FILTER (WHERE cto_output ->> 'decision' = 'request-changes')::int AS request_changes,
    COUNT(*) FILTER (WHERE cto_output ->> 'decision' = 'escalate-to-human')::int AS escalate,
    COUNT(*) FILTER (WHERE cto_output ->> 'decision' IS NULL)::int         AS no_decision,
    AVG(NULLIF(cto_output ->> 'confidence', '')::float)                    AS avg_confidence
FROM pr_trace
{where}
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

    async def list_recent(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        decision: str | None = None,
        workflow: str | None = None,
        range_token: str | None = None,
    ) -> list[dict[str, Any]]:
        assert self._conn is not None, "TraceReader not connected"
        if decision is not None and decision not in _DECISIONS:
            raise ValueError(f"unknown decision: {decision!r}")
        if workflow is not None and workflow not in _WORKFLOWS:
            raise ValueError(f"unknown workflow: {workflow!r}")
        if range_token is not None and range_token not in _RANGE_TO_INTERVAL:
            raise ValueError(f"unknown range token: {range_token!r}")

        sql, params = _build_list_sql(
            decision=decision, workflow=workflow, range_token=range_token
        )
        params.extend([limit, offset])
        async with self._conn.cursor() as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()
        return rows

    async def get(self, task_id: str) -> dict[str, Any] | None:
        assert self._conn is not None, "TraceReader not connected"
        async with self._conn.cursor() as cur:
            await cur.execute(_DETAIL_SQL, (task_id,))
            return await cur.fetchone()

    async def stats_decisions(self, range_token: str = "24h") -> dict[str, Any]:
        """Aggregate decision distribution + avg confidence over a window.

        ``range_token`` must be one of ``_RANGE_TO_INTERVAL``; an unknown
        value raises ``ValueError`` (the route validates before calling).
        """
        assert self._conn is not None, "TraceReader not connected"
        if range_token not in _RANGE_TO_INTERVAL:
            raise ValueError(f"unknown range token: {range_token!r}")
        interval = _RANGE_TO_INTERVAL[range_token]
        sql = _decision_stats_sql(with_window=interval is not None)
        params: tuple[Any, ...] = (interval,) if interval is not None else ()
        async with self._conn.cursor() as cur:
            await cur.execute(sql, params)
            row = await cur.fetchone()
        # Empty table → all zeros, avg None.
        row = row or {
            "total": 0,
            "auto_merge": 0,
            "request_changes": 0,
            "escalate": 0,
            "no_decision": 0,
            "avg_confidence": None,
        }
        total = row["total"] or 0
        escalation_rate = (row["escalate"] / total) if total else 0.0
        return {
            "range": range_token,
            "total": total,
            "auto_merge": row["auto_merge"],
            "request_changes": row["request_changes"],
            "escalate": row["escalate"],
            "no_decision": row["no_decision"],
            "escalation_rate": escalation_rate,
            "avg_confidence": row["avg_confidence"],
        }
