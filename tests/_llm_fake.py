"""Test helpers for faking ``claude_agent_sdk.query``.

Personas + monolithic_review now route through ``agents.llm.call_text``
which calls ``query()``. Tests that need to provide canned outputs
monkey-patch ``agents.llm.query`` to route by ``options.system_prompt``
identity, mirroring the previous AsyncAnthropic mock pattern.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock


def persona_for_system(system_prompt: str) -> str:
    """Identify which persona is being called from its prompt header.

    Mirrors the legacy logic in test_pipeline_smoke.py. Specialists fall
    through to ``"unknown"`` and callers must tag them by additional
    header inspection.
    """
    head = system_prompt.lstrip().splitlines()[0] if system_prompt else ""
    if "디스패처" in head or "dispatcher" in head.lower():
        return "dispatcher"
    if "CTO" in head:
        return "cto"
    if "보안 lead" in head:
        return "security_lead"
    if "품질 lead" in head:
        return "quality_lead"
    if "운영 lead" in head:
        return "ops_lead"
    if "호환성 lead" in head:
        return "compatibility_lead"
    if "제품·UX lead" in head:
        return "product_ux_lead"
    return "unknown"


def fake_query_factory(
    canned: dict[str, dict],
    *,
    classify: Callable[[str], str] | None = None,
) -> Callable[..., AsyncIterator[Any]]:
    """Build a fake ``query()`` async generator that yields canned JSON.

    ``canned`` maps persona id → JSON object the persona should return.
    ``classify`` overrides ``persona_for_system`` for callers that need
    to recognize specialist prompts (looking at multiple header lines).
    """
    classifier = classify or persona_for_system
    called: list[str] = []

    async def fake_query(*, prompt, options):
        system = ""
        if options is not None and options.system_prompt:
            system = options.system_prompt
        persona = classifier(system)
        called.append(persona)
        if persona not in canned:
            raise AssertionError(
                f"no canned response for persona={persona!r}; "
                f"available={sorted(canned)}"
            )
        text = f"```json\n{json.dumps(canned[persona], ensure_ascii=False)}\n```"
        yield AssistantMessage(
            content=[TextBlock(text=text)],
            model=options.model or "test-model",
        )
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="test-session",
            result=text,
            usage={"input_tokens": 100, "output_tokens": 50},
            model_usage={
                options.model or "test-model": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                }
            },
        )

    fake_query.called = called  # type: ignore[attr-defined]
    return fake_query


def install(monkeypatch, fake_query: Callable[..., AsyncIterator[Any]]) -> None:
    """Patch the ``query`` reference inside ``agents.llm``."""
    monkeypatch.setattr("agents.llm.query", fake_query)
