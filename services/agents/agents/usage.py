"""Per-task LLM token usage accumulation.

Each persona call records its token counts into a context-local
``UsageAccumulator``. The workflow consumer wraps a single task run in
``usage_scope()`` and reads ``totals()`` afterwards to attach to the
trace row. Context isolation matters because the agents service can
process multiple tasks concurrently — a global accumulator would
intermix counts.

Cache token columns reflect Anthropic's prompt-caching response fields
(``cache_read_input_tokens`` / ``cache_creation_input_tokens``); both
are zero for callers that don't enable caching.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UsageRecord:
    persona_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class UsageAccumulator:
    calls: list[UsageRecord] = field(default_factory=list)

    def record(
        self,
        *,
        persona_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        self.calls.append(
            UsageRecord(
                persona_id=persona_id,
                model=model,
                input_tokens=int(input_tokens or 0),
                output_tokens=int(output_tokens or 0),
                cache_read_tokens=int(cache_read_tokens or 0),
                cache_creation_tokens=int(cache_creation_tokens or 0),
            )
        )

    def totals(self) -> dict[str, Any]:
        if not self.calls:
            return {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "by_model": {},
            }
        # Per-model breakdown — needed at read time for cost calc since
        # opus/sonnet have different unit prices.
        by_model: dict[str, dict[str, int]] = {}
        for c in self.calls:
            slot = by_model.setdefault(
                c.model,
                {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_creation_tokens": 0,
                },
            )
            slot["calls"] += 1
            slot["input_tokens"] += c.input_tokens
            slot["output_tokens"] += c.output_tokens
            slot["cache_read_tokens"] += c.cache_read_tokens
            slot["cache_creation_tokens"] += c.cache_creation_tokens
        return {
            "calls": len(self.calls),
            "input_tokens": sum(c.input_tokens for c in self.calls),
            "output_tokens": sum(c.output_tokens for c in self.calls),
            "cache_read_tokens": sum(c.cache_read_tokens for c in self.calls),
            "cache_creation_tokens": sum(c.cache_creation_tokens for c in self.calls),
            "by_model": by_model,
        }


_current: contextvars.ContextVar[UsageAccumulator | None] = contextvars.ContextVar(
    "agents_usage_accumulator", default=None
)


def current() -> UsageAccumulator | None:
    """The active accumulator, if any. Personas use this to opt-in
    record their token usage; in tests / dry-runs without a scope, the
    record call is a no-op."""
    return _current.get()


@contextmanager
def usage_scope() -> Iterator[UsageAccumulator]:
    acc = UsageAccumulator()
    token = _current.set(acc)
    try:
        yield acc
    finally:
        _current.reset(token)
