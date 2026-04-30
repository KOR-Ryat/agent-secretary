"""Redis Streams publisher for raw_events."""

from agent_secretary_schemas import RawEvent
from redis.asyncio import Redis

STREAM_RAW_EVENTS = "raw_events"


class EventPublisher:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, event: RawEvent) -> str:
        message = {"event": event.model_dump_json()}
        return await self._redis.xadd(STREAM_RAW_EVENTS, message)

    async def close(self) -> None:
        await self._redis.aclose()
