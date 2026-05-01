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
    q: str | None = None,
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

    if q:
        # OR across the IDs and the JSONB-as-text view of pr_metadata.
        # ILIKE works on TEXT (task_id/event_id) directly; pr_metadata
        # is JSONB and gets coerced via ::text so substring matches hit
        # repo full_name + PR title without per-field SQL fan-out.
        like = f"%{q}%"
        where_clauses.append(
            "(task_id ILIKE %s OR event_id ILIKE %s OR pr_metadata::text ILIKE %s)"
        )
        params.extend([like, like, like])

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
        q: str | None = None,
    ) -> list[dict[str, Any]]:
        assert self._conn is not None, "TraceReader not connected"
        if decision is not None and decision not in _DECISIONS:
            raise ValueError(f"unknown decision: {decision!r}")
        if workflow is not None and workflow not in _WORKFLOWS:
            raise ValueError(f"unknown workflow: {workflow!r}")
        if range_token is not None and range_token not in _RANGE_TO_INTERVAL:
            raise ValueError(f"unknown range token: {range_token!r}")

        sql, params = _build_list_sql(
            decision=decision, workflow=workflow, range_token=range_token, q=q
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

    async def stats_by_dimension(
        self, dimension: str, range_token: str = "24h", *, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Decision distribution grouped by repo or source channel.

        ``dimension`` must be ``"repo"`` (groups by repo_full_name) or
        ``"channel"`` (groups by source_channel). Rows where the chosen
        column is NULL are skipped — they'd just be a meaningless
        bucket. Order: total DESC, then escalation DESC for tiebreak so
        risky high-volume sources surface first.
        """
        assert self._conn is not None, "TraceReader not connected"
        if range_token not in _RANGE_TO_INTERVAL:
            raise ValueError(f"unknown range token: {range_token!r}")
        if dimension == "repo":
            column = "repo_full_name"
        elif dimension == "channel":
            column = "source_channel"
        else:
            raise ValueError(f"unknown dimension: {dimension!r}")
        interval = _RANGE_TO_INTERVAL[range_token]

        time_filter = ""
        params: list[Any] = []
        if interval is not None:
            time_filter = "AND completed_at >= NOW() - %s::interval"
            params.append(interval)
        params.append(limit)

        decision_expr = "cto_output ->> 'decision'"
        sql = f"""
        SELECT
            {column} AS dim,
            COUNT(*)::int AS total,
            COUNT(*) FILTER (WHERE {decision_expr} = 'auto-merge')::int
                AS auto_merge,
            COUNT(*) FILTER (WHERE {decision_expr} = 'request-changes')::int
                AS request_changes,
            COUNT(*) FILTER (WHERE {decision_expr} = 'escalate-to-human')::int
                AS escalate,
            AVG(NULLIF(cto_output ->> 'confidence', '')::float)
                AS avg_confidence
        FROM pr_trace
        WHERE completed_at IS NOT NULL
          AND {column} IS NOT NULL
          {time_filter}
        GROUP BY {column}
        ORDER BY total DESC, escalate DESC
        LIMIT %s
        """
        async with self._conn.cursor() as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()
        return rows

    async def stats_operations(self, range_token: str = "24h") -> dict[str, Any]:
        """Aggregate token usage + latency over a window.

        Returns:
          - per-model token totals (input / output / cache_read / cache_create)
          - estimated USD cost (computed in the API layer using
            ``agent_secretary_config.cost_usd`` so price changes don't
            require a database backfill)
          - p50/p95/avg duration_ms across all completed runs

        The DB query just returns rows; cost calc and percentile picks
        happen in Python — keeps the SQL portable and the price table
        in one place.
        """
        assert self._conn is not None, "TraceReader not connected"
        if range_token not in _RANGE_TO_INTERVAL:
            raise ValueError(f"unknown range token: {range_token!r}")
        interval = _RANGE_TO_INTERVAL[range_token]

        where = "WHERE completed_at IS NOT NULL"
        params: tuple[Any, ...] = ()
        if interval is not None:
            where += " AND completed_at >= NOW() - %s::interval"
            params = (interval,)

        sql = f"""
        SELECT token_usage, duration_ms, workflow
        FROM pr_trace
        {where}
        """
        async with self._conn.cursor() as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()
        return {"range": range_token, "rows": rows}

    async def list_ab_pair(self, event_id: str) -> list[dict[str, Any]]:
        """Return both primary + shadow traces for a single event_id.

        Up to two rows: one with workflow=`pr_review` (primary) and one
        with workflow=`pr_review_monolithic` (shadow). Order:
        primary first, shadow second.
        """
        assert self._conn is not None, "TraceReader not connected"
        sql = """
        SELECT
            task_id, event_id, workflow, source_channel,
            pr_metadata, dispatcher_output, specialist_outputs,
            lead_outputs, cto_output, risk_metadata,
            summary_markdown, detail_markdown, human_decision,
            created_at, completed_at
        FROM pr_trace
        WHERE event_id = %s
          AND workflow IN ('pr_review', 'pr_review_monolithic')
        ORDER BY workflow ASC  -- 'pr_review' < 'pr_review_monolithic'
        """
        async with self._conn.cursor() as cur:
            await cur.execute(sql, (event_id,))
            return await cur.fetchall()

    async def stats_ab(self, range_token: str = "24h") -> dict[str, Any]:
        """Aggregate A/B agreement: rate of pr_review vs pr_review_monolithic
        decisions matching, and the most recent disagreements.

        Only includes events that have BOTH workflows completed. Events
        with one side still in flight (or AB mode disabled) are skipped.
        """
        assert self._conn is not None, "TraceReader not connected"
        if range_token not in _RANGE_TO_INTERVAL:
            raise ValueError(f"unknown range token: {range_token!r}")
        interval = _RANGE_TO_INTERVAL[range_token]

        time_filter = ""
        params: tuple[Any, ...] = ()
        if interval is not None:
            time_filter = "AND a.created_at >= NOW() - %s::interval"
            params = (interval,)

        sql = f"""
        SELECT
            a.event_id,
            a.task_id        AS primary_task_id,
            b.task_id        AS shadow_task_id,
            a.cto_output ->> 'decision'   AS primary_decision,
            b.cto_output ->> 'decision'   AS shadow_decision,
            a.cto_output ->> 'confidence' AS primary_confidence,
            b.cto_output ->> 'confidence' AS shadow_confidence,
            a.created_at
        FROM pr_trace a
        JOIN pr_trace b
          ON a.event_id = b.event_id
         AND a.workflow = 'pr_review'
         AND b.workflow = 'pr_review_monolithic'
        WHERE a.completed_at IS NOT NULL
          AND b.completed_at IS NOT NULL
          {time_filter}
        ORDER BY a.created_at DESC
        LIMIT 50
        """
        async with self._conn.cursor() as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()

        agree = sum(1 for r in rows if r["primary_decision"] == r["shadow_decision"])
        total = len(rows)
        return {
            "range": range_token,
            "total_pairs": total,
            "agree": agree,
            "disagree": total - agree,
            "agreement_rate": (agree / total) if total else 0.0,
            "pairs": rows,
        }

    async def stats_confidence(self, range_token: str = "24h") -> dict[str, Any]:
        """Histogram of CTO confidence scores into 10 bins of width 0.1.

        Bin i covers ``[i * 0.1, (i+1) * 0.1)`` for i in 0..8 and
        ``[0.9, 1.0]`` for i=9 (closed at the top so a perfect 1.0 lands
        in the last bin instead of overflowing). Rows where the CTO did
        not record a confidence are excluded — they contribute to the
        ``no_decision`` counter on /api/stats/decisions instead.
        """
        assert self._conn is not None, "TraceReader not connected"
        if range_token not in _RANGE_TO_INTERVAL:
            raise ValueError(f"unknown range token: {range_token!r}")
        interval = _RANGE_TO_INTERVAL[range_token]

        # GREATEST/LEAST clamp keeps malformed (>1 or <0) values inside
        # the visible bins instead of silently skipping them.
        where = (
            "WHERE completed_at IS NOT NULL "
            "AND cto_output ->> 'confidence' IS NOT NULL "
            "AND cto_output ->> 'confidence' <> ''"
        )
        if interval is not None:
            where += " AND completed_at >= NOW() - %s::interval"
        sql = f"""
        SELECT
            GREATEST(0, LEAST(9,
                FLOOR((cto_output ->> 'confidence')::float * 10)::int
            )) AS bin,
            COUNT(*)::int AS count
        FROM pr_trace
        {where}
        GROUP BY bin
        ORDER BY bin
        """
        params: tuple[Any, ...] = (interval,) if interval is not None else ()
        async with self._conn.cursor() as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()

        counts = [0] * 10
        for r in rows:
            counts[r["bin"]] = r["count"]
        return {
            "range": range_token,
            "bins": [
                {"lo": round(i * 0.1, 1), "hi": round((i + 1) * 0.1, 1), "count": counts[i]}
                for i in range(10)
            ],
            "total": sum(counts),
        }

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
