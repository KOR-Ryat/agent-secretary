"""Tests for the pr_review_monolithic workflow (issue #2 Case B).

Mocks `AsyncAnthropic.messages.create` to return canned JSON; the
workflow runner is responsible for parsing + attaching the
deterministically-computed risk_metadata.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = REPO_ROOT / "prompts"


def _settings(prompts_dir: Path):
    from agents.config import Settings

    return Settings(
        redis_url="redis://x",
        database_url=None,
        anthropic_api_key="dummy",
        log_level="WARNING",
        consumer_group="t",
        consumer_name="t1",
        prompts_dir=str(prompts_dir),
        model_cto="claude-opus-4-7",
        model_default="claude-sonnet-4-6",
        report_base_url=None,
    )


def _mock_client_with(canned_json: dict):
    response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=f"```json\n{json.dumps(canned_json, ensure_ascii=False)}\n```",
            )
        ],
        usage=SimpleNamespace(input_tokens=100, output_tokens=200),
    )
    return SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=response))
    )


def test_parse_output_happy_path():
    from agent_secretary_schemas.personas import RiskMetadata
    from agents.workflows.monolithic_review import _parse_output

    risk = RiskMetadata(
        high_risk_paths_touched=[],
        lines_changed=10,
        test_ratio=0.5,
        dependency_changes=False,
    )
    text = (
        "preamble\n"
        "```json\n"
        '{"decision":"auto-merge","confidence":0.9,'
        '"reasoning":"clean diff","findings":[]}\n'
        "```\n"
    )
    out = _parse_output(text, risk)
    assert out.decision == "auto-merge"
    assert out.confidence == 0.9
    assert out.findings == []
    # Risk metadata is attached even though the agent didn't emit it.
    assert out.risk_metadata.lines_changed == 10
    assert out.risk_metadata.test_ratio == 0.5


def test_parse_output_with_findings_carries_domain():
    from agent_secretary_schemas.personas import RiskMetadata
    from agents.workflows.monolithic_review import _parse_output

    risk = RiskMetadata()
    text = (
        "```json\n"
        '{"decision":"escalate-to-human","confidence":0.4,"reasoning":"x",'
        '"findings":['
        '{"domain":"security","severity":"blocking","location":"auth/x.py:1",'
        '"description":"missing","threat_or_impact":"breach"}'
        ']}\n'
        "```"
    )
    out = _parse_output(text, risk)
    assert len(out.findings) == 1
    f = out.findings[0]
    assert f.domain == "security"
    assert f.severity == "blocking"


def test_parse_output_rejects_invalid_domain():
    """Pydantic rejects domains outside the Literal whitelist."""
    from agent_secretary_schemas.personas import RiskMetadata
    from agents.workflows.monolithic_review import (
        MonolithicReviewError,
        _parse_output,
    )

    risk = RiskMetadata()
    text = (
        "```json\n"
        '{"decision":"auto-merge","confidence":0.5,"reasoning":"x",'
        '"findings":['
        '{"domain":"made_up","severity":"info","location":"x",'
        '"description":"x","threat_or_impact":"x"}'
        "]}\n"
        "```"
    )
    with pytest.raises(MonolithicReviewError):
        _parse_output(text, risk)


def test_parse_output_rejects_non_json_blob():
    from agent_secretary_schemas.personas import RiskMetadata
    from agents.workflows.monolithic_review import (
        MonolithicReviewError,
        _parse_output,
    )

    risk = RiskMetadata()
    with pytest.raises(MonolithicReviewError):
        _parse_output("just text, no JSON", risk)


@pytest.mark.asyncio
async def test_runner_returns_cto_output_and_risk_separately(monkeypatch, tmp_path):
    """`run()` returns a dict where cto_output carries the parsed monolithic
    output and risk_metadata is alongside it (matching trace store layout)."""
    os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("AGENT_WORKSPACE_DIR", str(tmp_path / "ws"))

    from agents.workflows.monolithic_review import MonolithicReviewRunner

    canned = {
        "decision": "auto-merge",
        "confidence": 0.85,
        "reasoning": "변경은 단순하고 우려 없음.",
        "findings": [],
    }
    client = _mock_client_with(canned)
    runner = MonolithicReviewRunner(client, _settings(PROMPTS_DIR))

    result = await runner.run(
        {
            "pr": {
                "title": "fix: x",
                "changed_files": ["api/items.py", "tests/test_items.py"],
                "diff_stats": {"additions": 30, "deletions": 5},
                "diff": "",
            },
            "repo": {"full_name": "acme/widgets"},
        }
    )

    assert result["cto_output"]["decision"] == "auto-merge"
    assert result["cto_output"]["findings"] == []
    # Deterministic risk_metadata computed by the workflow runner, not the LLM.
    assert "lines_changed" in result["risk_metadata"]
    assert result["risk_metadata"]["lines_changed"] == 35
    # Summary + detail are workflow-rendered, not LLM-emitted.
    assert "monolithic" in result["summary_markdown"].lower()


@pytest.mark.asyncio
async def test_runner_dispatches_via_workflow_runner(monkeypatch, tmp_path):
    """WorkflowRunner routes the new workflow id to the monolithic runner."""
    os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("AGENT_WORKSPACE_DIR", str(tmp_path / "ws"))

    from agent_secretary_config import WORKFLOW_PR_REVIEW_MONOLITHIC
    from agents.runner import WorkflowRunner

    canned = {
        "decision": "auto-merge",
        "confidence": 0.85,
        "reasoning": "ok",
        "findings": [],
    }
    client = _mock_client_with(canned)
    wr = WorkflowRunner(client, _settings(PROMPTS_DIR))

    out = await wr.run(
        WORKFLOW_PR_REVIEW_MONOLITHIC,
        {
            "pr": {"title": "x", "changed_files": [], "diff_stats": {}},
            "repo": {"full_name": "x/y"},
        },
    )
    assert out["cto_output"]["decision"] == "auto-merge"
