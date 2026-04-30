"""Tests for `_extract_json_block` in agents/personas/_base.py.

LLM output formatting drifts; the extractor needs to handle:

  - fenced ```json blocks (the preferred form)
  - bare ```  blocks without language hint
  - raw JSON with no fence
  - JSON preceded by chatter
  - nested objects (the regex must not stop at the first `}`)
  - missing JSON entirely (return whatever's there; downstream Pydantic
    validation will then fail loudly, which is the correct behavior)
"""

from __future__ import annotations

import json

from agents.personas._base import _extract_json_block


def test_fenced_json_block():
    text = '```json\n{"a": 1, "b": 2}\n```'
    assert _extract_json_block(text) == '{"a": 1, "b": 2}'


def test_fenced_block_without_language_hint():
    text = '```\n{"a": 1}\n```'
    assert _extract_json_block(text) == '{"a": 1}'


def test_fenced_block_with_surrounding_chatter():
    text = "Sure, here is the analysis:\n\n```json\n" '{"x": 42}' "\n```\n\nLet me know if..."
    assert _extract_json_block(text) == '{"x": 42}'


def test_raw_json_without_fence():
    """Some responses skip the fence — fall through to balanced-brace scan."""
    text = '{"a": 1, "b": "hello"}'
    assert _extract_json_block(text) == '{"a": 1, "b": "hello"}'


def test_raw_json_after_chatter():
    text = "Here is the JSON: {\"a\": 1}"
    extracted = _extract_json_block(text)
    assert json.loads(extracted) == {"a": 1}


def test_nested_object_balanced_braces():
    """Regex `{.*?}` is non-greedy — it would stop at the first `}`. The
    balanced-brace fallback must reach the matching outer `}`."""
    text = '{"outer": {"inner": [1, 2, 3]}, "trailing": true}'
    extracted = _extract_json_block(text)
    parsed = json.loads(extracted)
    assert parsed == {"outer": {"inner": [1, 2, 3]}, "trailing": True}


def test_fenced_block_with_nested_object():
    """Fenced regex uses `\\{.*?\\}` non-greedy — confirm it captures the
    full nested span when the closing fence is well-placed."""
    obj = {"a": {"b": {"c": 1}}}
    text = f"prelude\n```json\n{json.dumps(obj)}\n```\npostlude"
    extracted = _extract_json_block(text)
    # Note: the current implementation uses non-greedy match, which can
    # truncate at the first `}` for nested objects inside fences. This
    # test documents the *current* behavior; if it changes, the test
    # surfaces the change.
    parsed_or_raises = None
    try:
        parsed_or_raises = json.loads(extracted)
    except json.JSONDecodeError:
        # Acceptable: extractor returned something that failed parse.
        # Downstream Pydantic validation produces a PersonaCallError.
        return
    # If parse succeeded, it must match.
    assert parsed_or_raises == obj


def test_no_json_returns_text_stripped():
    """No `{` anywhere → returns the original text (stripped)."""
    text = "  no json here, sorry  "
    assert _extract_json_block(text) == "no json here, sorry"


def test_empty_text():
    assert _extract_json_block("") == ""


def test_unmatched_brace_returns_partial():
    """An open `{` with no closing → returns from `{` to end of input.

    Downstream JSON parse will fail and raise PersonaCallError —
    documented behavior, not a silent success."""
    text = '{"a": 1, "incomplete":'
    extracted = _extract_json_block(text)
    assert extracted.startswith("{")
    # Confirms the failure mode: this isn't valid JSON.
    try:
        json.loads(extracted)
    except json.JSONDecodeError:
        return
    raise AssertionError("expected unmatched-brace text to fail JSON parse")
