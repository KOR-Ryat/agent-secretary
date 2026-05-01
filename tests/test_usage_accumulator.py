"""Tests for the per-task usage accumulator.

Each persona call records token counts into a contextvar-scoped
accumulator. The agents service wraps a single task run in
``usage_scope()`` so two tasks running in parallel don't intermix
counts. These tests exercise that isolation directly without spinning
up the full Anthropic client.
"""

from __future__ import annotations

import asyncio

import pytest


def test_record_outside_scope_is_noop():
    from agents.usage import current

    # No active scope → current() returns None and recording is a no-op.
    assert current() is None


def test_totals_within_scope():
    from agents.usage import usage_scope

    with usage_scope() as acc:
        acc.record(persona_id="p1", model="m1", input_tokens=10, output_tokens=2)
        acc.record(persona_id="p2", model="m1", input_tokens=20, output_tokens=4)
        totals = acc.totals()

    assert totals["calls"] == 2
    assert totals["input_tokens"] == 30
    assert totals["output_tokens"] == 6
    assert totals["by_model"]["m1"]["calls"] == 2


def test_totals_groups_by_model():
    """Per-model breakdown is essential for cost calc — opus/sonnet have
    different unit prices, so we can't sum them blindly."""
    from agents.usage import usage_scope

    with usage_scope() as acc:
        acc.record(persona_id="cto", model="opus", input_tokens=100, output_tokens=50)
        acc.record(persona_id="lead", model="sonnet", input_tokens=200, output_tokens=80)
        acc.record(persona_id="spec", model="sonnet", input_tokens=150, output_tokens=40)
        totals = acc.totals()

    assert totals["by_model"]["opus"]["calls"] == 1
    assert totals["by_model"]["opus"]["input_tokens"] == 100
    assert totals["by_model"]["sonnet"]["calls"] == 2
    assert totals["by_model"]["sonnet"]["input_tokens"] == 350
    assert totals["by_model"]["sonnet"]["output_tokens"] == 120


def test_empty_scope_returns_zeros_not_none():
    """Trace writer relies on the contract: totals() always returns the
    full key set, even with no calls — avoids a JSONB null vs empty-object
    ambiguity downstream."""
    from agents.usage import usage_scope

    with usage_scope() as acc:
        totals = acc.totals()
    assert totals["calls"] == 0
    assert totals["input_tokens"] == 0
    assert totals["by_model"] == {}


def test_cache_tokens_default_to_zero():
    """Callers without prompt-caching pass missing/None — coerce to 0."""
    from agents.usage import usage_scope

    with usage_scope() as acc:
        acc.record(
            persona_id="p", model="m",
            input_tokens=10, output_tokens=2,
            cache_read_tokens=None, cache_creation_tokens=None,
        )
        t = acc.totals()
    assert t["cache_read_tokens"] == 0
    assert t["cache_creation_tokens"] == 0


def test_nested_scopes_are_isolated():
    """An outer accumulator must not see records made inside an inner
    scope (this guards against shared-state bugs if a workflow ever
    nests scopes for sub-stages)."""
    from agents.usage import current, usage_scope

    with usage_scope() as outer:
        outer.record(persona_id="o", model="m", input_tokens=1, output_tokens=1)
        with usage_scope() as inner:
            inner.record(persona_id="i", model="m", input_tokens=99, output_tokens=99)
            assert current() is inner
        # Back to outer.
        assert current() is outer

    assert outer.totals()["input_tokens"] == 1
    assert inner.totals()["input_tokens"] == 99


@pytest.mark.asyncio
async def test_concurrent_tasks_dont_share_accumulator():
    """Two tasks running in parallel via asyncio.gather must each see
    only their own records — contextvars must propagate per-task."""
    from agents.usage import current, usage_scope

    async def task(record_count: int) -> int:
        with usage_scope() as acc:
            for _ in range(record_count):
                # tiny await so the scheduler interleaves the two tasks.
                await asyncio.sleep(0)
                acc.record(persona_id="p", model="m", input_tokens=1, output_tokens=0)
            assert current() is acc
            return acc.totals()["calls"]

    a, b = await asyncio.gather(task(3), task(7))
    assert a == 3
    assert b == 7


def test_persona_base_records_when_scope_active(monkeypatch):
    """PersonaAgent.call should append to the active accumulator. We
    stub the Anthropic client to avoid a real API call."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from agents.personas._base import PersonaAgent
    from agents.usage import usage_scope
    from pydantic import BaseModel

    class _Out(BaseModel):
        ok: bool

    class _P(PersonaAgent[_Out]):
        persona_id = "test_persona"
        prompt_path = "x.md"
        output_model = _Out
        model = "claude-test"

    # Bypass __init__ (it reads a prompt file) — fabricate the agent.
    p = _P.__new__(_P)
    text_block = SimpleNamespace(type="text", text='```json\n{"ok": true}\n```')
    fake_response = SimpleNamespace(
        content=[text_block],
        usage=SimpleNamespace(
            input_tokens=42, output_tokens=7,
            cache_read_input_tokens=0, cache_creation_input_tokens=0,
        ),
    )
    p._client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    p._system_prompt = "system"

    async def _go():
        with usage_scope() as acc:
            await p.call({"foo": "bar"})
            return acc.totals()

    totals = asyncio.run(_go())
    assert totals["calls"] == 1
    assert totals["input_tokens"] == 42
    assert totals["output_tokens"] == 7
    assert totals["by_model"]["claude-test"]["calls"] == 1


def test_persona_base_does_not_crash_without_scope():
    """Outside usage_scope() (e.g. unit tests calling PersonaAgent
    directly) the call must still succeed — recording is a no-op."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from agents.personas._base import PersonaAgent
    from pydantic import BaseModel

    class _Out(BaseModel):
        ok: bool

    class _P(PersonaAgent[_Out]):
        persona_id = "test_persona"
        prompt_path = "x.md"
        output_model = _Out
        model = "claude-test"

    p = _P.__new__(_P)
    text_block = SimpleNamespace(type="text", text='```json\n{"ok": true}\n```')
    fake_response = SimpleNamespace(
        content=[text_block],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    p._client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    p._system_prompt = "sys"

    out = asyncio.run(p.call({}))
    assert out.ok is True
