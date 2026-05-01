"""Read-only Redis Streams health probe.

Exposes per-stream depth, oldest-entry age, and per-consumer-group
pending counts so the dashboard can surface backlogs and stuck
consumers without operators having to shell into Redis.
"""

from __future__ import annotations

from typing import Any

from agent_secretary_config import (
    STREAM_RAW_EVENTS,
    STREAM_RAW_EVENTS_DLQ,
    STREAM_RESULTS,
    STREAM_RESULTS_DLQ,
    STREAM_TASKS,
    STREAM_TASKS_DLQ,
)
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from ingress.logging import get_logger

log = get_logger("ingress.dashboard.health")


# Pairs of (live stream, DLQ) — the UI groups them so a single failed
# message doesn't get separated from its source queue.
_STREAM_PAIRS: list[tuple[str, str]] = [
    (STREAM_RAW_EVENTS, STREAM_RAW_EVENTS_DLQ),
    (STREAM_TASKS, STREAM_TASKS_DLQ),
    (STREAM_RESULTS, STREAM_RESULTS_DLQ),
]


def _decode(v: Any) -> Any:
    """bytes → str so JSON-serializing the snapshot works."""
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return v


def _age_seconds_from_id(stream_id: str | bytes, now_ms: int) -> float | None:
    """Stream IDs are ``<unix_ms>-<seq>`` — pull the timestamp out."""
    s = _decode(stream_id)
    if not isinstance(s, str) or "-" not in s:
        return None
    try:
        ts_ms = int(s.split("-", 1)[0])
    except ValueError:
        return None
    return max(0.0, (now_ms - ts_ms) / 1000.0)


class QueueHealth:
    """Async Redis Streams health probe.

    Holds a single shared connection. The dashboard does ~1 req every
    30s — no connection-pool overhead needed.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._redis: Redis | None = None

    async def connect(self) -> None:
        self._redis = Redis.from_url(self._url, decode_responses=False)
        # ping eagerly so we fail loud if the URL is wrong.
        await self._redis.ping()
        log.info("dashboard.queue_health.connected")

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def snapshot(self) -> dict[str, Any]:
        assert self._redis is not None, "QueueHealth not connected"
        # Use Redis-side TIME so age math doesn't drift if the
        # dashboard host clock is out of sync with the broker.
        sec, micro = await self._redis.time()
        now_ms = int(sec) * 1000 + int(micro) // 1000

        pairs: list[dict[str, Any]] = []
        total_depth = 0
        total_dlq = 0
        for live, dlq in _STREAM_PAIRS:
            live_info = await self._stream_info(live, now_ms, with_groups=True)
            dlq_info = await self._stream_info(dlq, now_ms, with_groups=False)
            total_depth += live_info["length"]
            total_dlq += dlq_info["length"]
            pairs.append({"live": live_info, "dlq": dlq_info})

        return {
            "now_ms": now_ms,
            "pairs": pairs,
            "total_depth": total_depth,
            "total_dlq": total_dlq,
        }

    async def _stream_info(
        self, name: str, now_ms: int, *, with_groups: bool
    ) -> dict[str, Any]:
        assert self._redis is not None
        # XLEN of a missing stream returns 0 — fine.
        length = int(await self._redis.xlen(name))
        oldest_age: float | None = None
        if length > 0:
            head = await self._redis.xrange(name, count=1)
            if head:
                oldest_age = _age_seconds_from_id(head[0][0], now_ms)

        groups: list[dict[str, Any]] = []
        if with_groups and length > 0:
            try:
                infos = await self._redis.xinfo_groups(name)
            except ResponseError:
                # Stream exists but no groups created — treat as empty.
                infos = []
            for g in infos:
                groups.append(
                    {
                        "name": _decode(g.get(b"name") or g.get("name")),
                        "pending": int(g.get(b"pending") or g.get("pending") or 0),
                        "consumers": int(g.get(b"consumers") or g.get("consumers") or 0),
                        "lag": _coerce_lag(g.get(b"lag") or g.get("lag")),
                    }
                )

        return {
            "name": name,
            "length": length,
            "oldest_age_seconds": oldest_age,
            "groups": groups,
        }


def _coerce_lag(v: Any) -> int | None:
    """Redis returns lag as int or None (when uncomputable)."""
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
