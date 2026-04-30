"""Trace store writer.

Writes one row per PR review to `pr_trace`. Used downstream for KPI
calculation (design.md §10) — CTO/human agreement, false-confident rate, etc.

`human_decision` is left NULL at write time and filled in later by a
GitHub webhook (Phase 1: not yet implemented; see design_server.md §12).

Schema is intentionally minimal — single denormalized table, JSONB for
nested structures. Optimize later when query patterns are known.
"""

from __future__ import annotations

import json

import psycopg
from agent_secretary_schemas import ResultEvent, TaskSpec
from psycopg.rows import dict_row

from agents.logging import get_logger

log = get_logger("agents.trace")

DDL = """
CREATE TABLE IF NOT EXISTS pr_trace (
    task_id          TEXT PRIMARY KEY,
    event_id         TEXT NOT NULL,
    workflow         TEXT NOT NULL,
    source_channel   TEXT NOT NULL,
    pr_metadata      JSONB NOT NULL,
    dispatcher_output JSONB,
    specialist_outputs JSONB,
    lead_outputs     JSONB,
    cto_output       JSONB,
    risk_metadata    JSONB,
    summary_markdown TEXT,
    human_decision   JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS pr_trace_event_id_idx ON pr_trace(event_id);
CREATE INDEX IF NOT EXISTS pr_trace_workflow_idx ON pr_trace(workflow);
CREATE INDEX IF NOT EXISTS pr_trace_created_at_idx ON pr_trace(created_at);
"""


class TraceStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn: psycopg.AsyncConnection | None = None

    async def connect(self) -> None:
        self._conn = await psycopg.AsyncConnection.connect(self._dsn, row_factory=dict_row)
        async with self._conn.cursor() as cur:
            await cur.execute(DDL)
        await self._conn.commit()
        log.info("trace.connected")

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def write(
        self,
        *,
        task: TaskSpec,
        result: ResultEvent,
        source_channel: str,
    ) -> None:
        assert self._conn is not None, "TraceStore.connect() must be called first"
        output = result.output
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO pr_trace (
                    task_id, event_id, workflow, source_channel,
                    pr_metadata, dispatcher_output, specialist_outputs,
                    lead_outputs, cto_output, risk_metadata,
                    summary_markdown, completed_at
                )
                VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s
                )
                ON CONFLICT (task_id) DO UPDATE SET
                    dispatcher_output = EXCLUDED.dispatcher_output,
                    specialist_outputs = EXCLUDED.specialist_outputs,
                    lead_outputs = EXCLUDED.lead_outputs,
                    cto_output = EXCLUDED.cto_output,
                    risk_metadata = EXCLUDED.risk_metadata,
                    summary_markdown = EXCLUDED.summary_markdown,
                    completed_at = EXCLUDED.completed_at
                """,
                (
                    task.task_id,
                    task.event_id,
                    task.workflow,
                    source_channel,
                    json.dumps(task.workflow_input.get("pr", {}), ensure_ascii=False),
                    json.dumps(output.get("dispatcher_output"), ensure_ascii=False),
                    json.dumps(output.get("specialist_outputs"), ensure_ascii=False),
                    json.dumps(output.get("lead_outputs"), ensure_ascii=False),
                    json.dumps(output.get("cto_output"), ensure_ascii=False),
                    json.dumps(output.get("risk_metadata"), ensure_ascii=False),
                    result.summary_markdown,
                    result.completed_at,
                ),
            )
        await self._conn.commit()
        log.info("trace.written", task_id=task.task_id)


class NoopTraceStore:
    """Fallback when DATABASE_URL is unset — useful for local dry runs."""

    async def connect(self) -> None:
        log.info("trace.noop")

    async def close(self) -> None:
        pass

    async def write(self, **kwargs) -> None:
        pass


def make_trace_store(database_url: str | None) -> TraceStore | NoopTraceStore:
    if database_url:
        return TraceStore(database_url)
    return NoopTraceStore()
