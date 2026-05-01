"""Monolithic PR review — Case B of the persona A/B test (issue #2).

A single Anthropic call processes the full PR with a checklist-style
system prompt covering all five domains (security/quality/ops/
compatibility/product_ux). Emits a `MonolithicReviewOutput` whose
shape mirrors a CtoOutput plus a flat `findings` list.

This workflow is independent — runnable on its own (no A/B wiring
needed). The classifier marks it as a *shadow task* (`shadow=True`,
see TaskSpec) when ab mode is enabled, so its result skips the
egress publish step and exists only as a row in pr_trace for later
comparison.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent_secretary_schemas.personas import (
    MonolithicReviewOutput,
    RiskMetadata,
)
from anthropic import AsyncAnthropic
from pydantic import ValidationError

from agents import usage as usage_mod
from agents.config import Settings
from agents.logging import get_logger
from agents.workflows.pr_review import _compute_risk_metadata

log = get_logger("agents.workflows.monolithic_review")

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_DEFAULT_MAX_TOKENS = 8192


class MonolithicReviewError(RuntimeError):
    """Raised when the agent's output can't be parsed into the expected shape."""


class MonolithicReviewRunner:
    def __init__(self, client: AsyncAnthropic, settings: Settings) -> None:
        self._client = client
        # Match A's *decision maker* (the CTO is Opus). Otherwise the A/B
        # comparison would conflate persona structure with model capability —
        # we want to isolate the "does persona separation help?" question.
        self._model = settings.model_cto
        prompts_dir = Path(settings.prompts_dir)
        self._system_prompt = (
            prompts_dir / "workflows" / "pr_review_monolithic.md"
        ).read_text(encoding="utf-8")

    async def run(self, workflow_input: dict[str, Any]) -> dict[str, Any]:
        pr = workflow_input.get("pr", {}) or {}
        repo_full_name = (workflow_input.get("repo") or {}).get("full_name")

        # Risk metadata is computed deterministically — same code path as A.
        # This way the A/B comparison isolates LLM behavior, not heuristic drift.
        risk = _compute_risk_metadata(pr, repo_full_name)

        log.info(
            "workflow.monolithic_review.start",
            pr_title=(pr.get("title") or "")[:60],
            repo=repo_full_name,
        )

        user_message = self._build_user_message(pr)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=_DEFAULT_MAX_TOKENS,
            system=self._system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        text = _extract_text(response)
        parsed = _parse_output(text, risk)

        acc = usage_mod.current()
        if acc is not None:
            acc.record(
                persona_id="monolithic_review",
                model=self._model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cache_read_tokens=getattr(
                    response.usage, "cache_read_input_tokens", 0
                ) or 0,
                cache_creation_tokens=getattr(
                    response.usage, "cache_creation_input_tokens", 0
                ) or 0,
            )

        log.info(
            "workflow.monolithic_review.complete",
            decision=parsed.decision,
            confidence=parsed.confidence,
            finding_count=len(parsed.findings),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        # The dict shape mirrors what trace.py expects: cto_output column
        # ends up holding the full monolithic output (decision/confidence/
        # reasoning/findings). risk_metadata stays in its own column.
        return {
            "cto_output": parsed.model_dump(),
            "risk_metadata": risk.model_dump(),
            "summary_markdown": _render_summary(parsed),
            "detail_markdown": _render_detail(parsed),
        }

    def _build_user_message(self, pr: dict[str, Any]) -> str:
        return (
            "다음 PR 을 시스템 프롬프트의 체크리스트와 결정 룰에 따라 검토하세요.\n\n"
            "```json\n"
            f"{json.dumps({'pr': pr}, ensure_ascii=False, indent=2)}\n"
            "```\n"
        )


# --- helpers ---------------------------------------------------------


def _extract_text(response) -> str:
    parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


def _parse_output(text: str, risk: RiskMetadata) -> MonolithicReviewOutput:
    """Parse fenced JSON from the agent and inflate to MonolithicReviewOutput.

    The agent doesn't emit `risk_metadata` (we tell it not to); we attach
    the deterministically-computed value here so the persisted shape is
    self-contained.
    """
    if not text:
        raise MonolithicReviewError("agent returned empty output")
    match = _FENCE_RE.search(text)
    candidate = match.group(1) if match else _balanced(text)
    if candidate is None:
        raise MonolithicReviewError(
            f"no JSON object found in agent output: {text[:200]!r}"
        )
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as e:
        raise MonolithicReviewError(f"agent output is not valid JSON: {e}") from e
    data["risk_metadata"] = risk.model_dump()
    try:
        return MonolithicReviewOutput.model_validate(data)
    except ValidationError as e:
        raise MonolithicReviewError(f"agent output failed schema: {e}") from e


def _balanced(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _render_summary(out: MonolithicReviewOutput) -> str:
    bcount = sum(1 for f in out.findings if f.severity == "blocking")
    wcount = sum(1 for f in out.findings if f.severity == "warning")
    return (
        f"## 🤖 PR review (monolithic, A/B Case B)\n\n"
        f"**Decision:** `{out.decision}` · **Confidence:** {out.confidence:.2f}\n\n"
        f"**Findings:** {len(out.findings)} total "
        f"({bcount} blocking, {wcount} warning)\n\n"
        f"_{out.reasoning}_\n"
    )


def _render_detail(out: MonolithicReviewOutput) -> str:
    if not out.findings:
        return ""
    lines = ["# Monolithic PR review — findings\n"]
    by_domain: dict[str, list] = {}
    for f in out.findings:
        by_domain.setdefault(f.domain, []).append(f)
    for domain, items in by_domain.items():
        lines.append(f"## {domain}")
        for f in items:
            lines.append(
                f"- **{f.severity}** `{f.location}` — {f.description}\n"
                f"  - _{f.threat_or_impact}_"
            )
        lines.append("")
    return "\n".join(lines)
