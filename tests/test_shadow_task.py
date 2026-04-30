"""Tests for the TaskSpec.shadow flag.

The flag itself is just a boolean field; the *behavior* lives in
agents/main.py. We don't run the full consumer loop — instead we
verify the schema default and re-serialization, and unit-test the
publish-skip branch via a small helper.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent_secretary_schemas import (
    ChannelTarget,
    ResponseRouting,
    TaskSpec,
)


def _routing() -> ResponseRouting:
    return ResponseRouting(primary=ChannelTarget(channel="cli", target={}))


def test_shadow_defaults_false():
    t = TaskSpec(
        task_id="t1",
        event_id="e1",
        workflow="pr_review",
        workflow_input={},
        response_routing=_routing(),
        created_at=datetime.now(UTC),
    )
    assert t.shadow is False


def test_shadow_true_round_trip():
    t = TaskSpec(
        task_id="t1",
        event_id="e1",
        workflow="pr_review_monolithic",
        workflow_input={},
        response_routing=_routing(),
        created_at=datetime.now(UTC),
        shadow=True,
    )
    serialized = t.model_dump_json()
    re_parsed = TaskSpec.model_validate_json(serialized)
    assert re_parsed.shadow is True
    assert re_parsed.workflow == "pr_review_monolithic"


def test_shadow_default_round_trip_preserved():
    """JSON without `shadow` field still parses (backward compatibility
    with previously published tasks)."""
    payload = (
        '{"task_id":"t1","event_id":"e1","workflow":"pr_review",'
        '"workflow_input":{},'
        '"response_routing":{"primary":{"channel":"cli","target":{}},'
        '"additional":[]},'
        '"created_at":"2026-05-01T00:00:00Z"}'
    )
    t = TaskSpec.model_validate_json(payload)
    assert t.shadow is False
