"""Core service consumer loop.

Reads RawEvents from `raw_events` stream, classifies, and publishes TaskSpec
to `tasks` stream. ack/dlq policy: ack on success, dlq after MAX_DELIVERIES.
"""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from core.classifier import UnclassifiedEvent, classify
from core.config import Settings
from core.logging import configure_logging, get_logger
from core.queue import MAX_DELIVERIES, CoreQueue

log = get_logger("core.main")


async def run() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    log.info("core.starting", redis_url=settings.redis_url)

    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    queue = CoreQueue(redis, settings.consumer_group, settings.consumer_name)
    await queue.ensure_group()
    log.info("core.consumer_ready", group=settings.consumer_group)

    try:
        async for message_id, event, delivery in queue.consume():
            log.info(
                "core.event.received",
                message_id=message_id,
                event_id=event.event_id,
                source=event.source_channel,
                delivery=delivery,
            )
            try:
                task = classify(event)
            except UnclassifiedEvent as e:
                if delivery >= MAX_DELIVERIES:
                    log.warning(
                        "core.event.dlq", event_id=event.event_id, reason=str(e)
                    )
                    await queue.to_dlq(message_id, event.model_dump_json(), str(e))
                else:
                    # Don't ack — let it retry. Practically, this won't be retried
                    # since the same code path will fail again, so we DLQ immediately.
                    log.warning(
                        "core.event.unclassified",
                        event_id=event.event_id,
                        reason=str(e),
                    )
                    await queue.to_dlq(message_id, event.model_dump_json(), str(e))
                continue

            await queue.publish_task(task)
            await queue.ack(message_id)
            log.info(
                "core.task.published",
                task_id=task.task_id,
                workflow=task.workflow,
                event_id=event.event_id,
            )
    finally:
        await queue.close()


if __name__ == "__main__":
    asyncio.run(run())
