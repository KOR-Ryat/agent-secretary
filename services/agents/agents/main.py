"""Agents service consumer loop.

Reads TaskSpec from `tasks` stream, runs the corresponding workflow,
publishes ResultEvent to `results` stream.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime

from agent_secretary_config import MAX_DELIVERIES
from agent_secretary_schemas import ResultEvent
from anthropic import AsyncAnthropic
from redis.asyncio import Redis

from agents import usage as usage_mod
from agents.config import Settings
from agents.logging import configure_logging, get_logger
from agents.queue import AgentsQueue
from agents.runner import UnknownWorkflowError, WorkflowRunner
from agents.summary import render_summary_markdown
from agents.trace import make_trace_store

log = get_logger("agents.main")


async def run() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    log.info(
        "agents.starting",
        redis_url=settings.redis_url,
        prompts_dir=settings.prompts_dir,
        model_default=settings.model_default,
        model_cto=settings.model_cto,
    )

    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    queue = AgentsQueue(redis, settings.consumer_group, settings.consumer_name)
    await queue.ensure_group()

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    runner = WorkflowRunner(client, settings)

    trace = make_trace_store(settings.database_url)
    await trace.connect()

    log.info("agents.consumer_ready", group=settings.consumer_group)

    try:
        async for message_id, task, delivery in queue.consume():
            log.info(
                "agents.task.received",
                message_id=message_id,
                task_id=task.task_id,
                workflow=task.workflow,
                delivery=delivery,
            )
            t_start = time.perf_counter()
            try:
                with usage_mod.usage_scope() as usage_acc:
                    output = await runner.run(task.workflow, task.workflow_input)
            except UnknownWorkflowError as e:
                log.warning("agents.workflow.unknown", task_id=task.task_id, reason=str(e))
                await queue.to_dlq(message_id, task.model_dump_json(), str(e))
                continue
            except Exception as e:
                log.error(
                    "agents.workflow.error",
                    task_id=task.task_id,
                    error=str(e),
                    delivery=delivery,
                )
                if delivery >= MAX_DELIVERIES:
                    await queue.to_dlq(message_id, task.model_dump_json(), str(e))
                # else leave un-acked → redis will redeliver
                continue

            # Workflows may opt in to providing their own summary/detail
            # (e.g., code_analyze → 메시지/파일). Otherwise the pr_review
            # markdown renderer takes over.
            summary = output.get("summary_markdown") or render_summary_markdown(output)
            detail = output.get("detail_markdown")

            # Public report URL — only when both REPORT_BASE_URL is configured
            # and the workflow actually produced a detail body to render.
            trace_url: str | None = None
            if settings.report_base_url and detail:
                trace_url = (
                    f"{settings.report_base_url.rstrip('/')}/static/reports/{task.task_id}"
                )

            result = ResultEvent(
                result_id=str(uuid.uuid4()),
                task_id=task.task_id,
                event_id=task.event_id,
                workflow=task.workflow,
                output=output,
                summary_markdown=summary,
                detail_markdown=detail,
                response_routing=task.response_routing,
                completed_at=datetime.now(UTC),
                trace_url=trace_url,
            )

            duration_ms = int((time.perf_counter() - t_start) * 1000)
            token_usage = usage_acc.totals()

            # Persist trace before publishing — if trace write fails, we'd
            # rather retry than emit a result without provenance.
            await trace.write(
                task=task,
                result=result,
                source_channel=task.response_routing.primary.channel,
                token_usage=token_usage,
                duration_ms=duration_ms,
            )

            if task.shadow:
                # Trace-only — no egress publish. Used by A/B comparator
                # tasks etc. so the user only sees the primary workflow.
                await queue.ack(message_id)
                log.info(
                    "agents.result.shadow",
                    task_id=task.task_id,
                    workflow=task.workflow,
                    decision=output.get("cto_output", {}).get("decision"),
                )
                continue

            await queue.publish_result(result)
            await queue.ack(message_id)
            log.info(
                "agents.result.published",
                task_id=task.task_id,
                result_id=result.result_id,
                decision=output.get("cto_output", {}).get("decision"),
            )
    finally:
        await trace.close()
        await queue.close()


if __name__ == "__main__":
    asyncio.run(run())
