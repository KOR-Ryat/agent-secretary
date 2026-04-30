"""Redis Streams consumer (tasks) + publisher (results)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from agent_secretary_config import (
    STREAM_RESULTS,
    STREAM_TASKS,
    STREAM_TASKS_DLQ,
)
from agent_secretary_schemas import ResultEvent, TaskSpec
from redis.asyncio import Redis
from redis.exceptions import ResponseError


class AgentsQueue:
    def __init__(self, redis: Redis, consumer_group: str, consumer_name: str) -> None:
        self._redis = redis
        self._group = consumer_group
        self._consumer = consumer_name

    async def ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(
                STREAM_TASKS, self._group, id="0", mkstream=True
            )
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def consume(self, block_ms: int = 5000) -> AsyncIterator[tuple[str, TaskSpec, int]]:
        while True:
            entries = await self._redis.xreadgroup(
                groupname=self._group,
                consumername=self._consumer,
                streams={STREAM_TASKS: ">"},
                count=1,
                block=block_ms,
            )
            if not entries:
                continue
            for _stream, messages in entries:
                for message_id, fields in messages:
                    raw = fields.get(b"task") or fields.get("task")
                    if raw is None:
                        continue
                    payload = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
                    task = TaskSpec.model_validate_json(payload)
                    delivery = await self._delivery_count(message_id)
                    yield message_id, task, delivery

    async def _delivery_count(self, message_id: bytes | str) -> int:
        info = await self._redis.xpending_range(
            STREAM_TASKS, self._group, min=message_id, max=message_id, count=1
        )
        if not info:
            return 1
        return int(info[0]["times_delivered"])

    async def ack(self, message_id: bytes | str) -> None:
        await self._redis.xack(STREAM_TASKS, self._group, message_id)

    async def to_dlq(self, message_id: bytes | str, task_json: str, reason: str) -> None:
        await self._redis.xadd(
            STREAM_TASKS_DLQ,
            {"task": task_json, "reason": reason, "original_id": str(message_id)},
        )
        await self.ack(message_id)

    async def publish_result(self, result: ResultEvent) -> str:
        return await self._redis.xadd(STREAM_RESULTS, {"result": result.model_dump_json()})

    async def close(self) -> None:
        await self._redis.aclose()


__all__ = ["AgentsQueue"]
