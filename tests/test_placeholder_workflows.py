"""Placeholder workflow tests."""

from __future__ import annotations

import pytest
from agent_secretary_config import WORKFLOW_CODE_MODIFY, WORKFLOW_LINEAR_ISSUE


@pytest.mark.asyncio
async def test_code_modify_placeholder_returns_message_and_detail():
    from agents.workflows.placeholder import PlaceholderRunner

    out = await PlaceholderRunner().run(
        WORKFLOW_CODE_MODIFY, {"channel_name": "if-payment-production"}
    )
    assert out["placeholder"] is True
    assert "🚧" in out["summary_markdown"]
    assert "구현 중" in out["summary_markdown"]
    assert "code_modify" in out["detail_markdown"]


@pytest.mark.asyncio
async def test_linear_issue_placeholder_returns_message_and_detail():
    from agents.workflows.placeholder import PlaceholderRunner

    out = await PlaceholderRunner().run(WORKFLOW_LINEAR_ISSUE, {})
    assert out["placeholder"] is True
    assert "🚧" in out["summary_markdown"]
    assert "Linear" in out["detail_markdown"]


@pytest.mark.asyncio
async def test_runner_dispatches_placeholders(monkeypatch, tmp_path):
    """WorkflowRunner routes the placeholder workflows without invoking an LLM."""
    import os

    os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("AGENT_WORKSPACE_DIR", str(tmp_path / "ws"))

    from pathlib import Path

    from agents.config import Settings
    from agents.runner import WorkflowRunner
    from anthropic import AsyncAnthropic

    repo_root = Path(__file__).resolve().parents[1]
    s = Settings(
        redis_url="redis://x",
        database_url=None,
        anthropic_api_key="dummy",
        log_level="WARNING",
        consumer_group="t",
        consumer_name="t1",
        prompts_dir=str(repo_root / "prompts"),
        model_cto="claude-opus-4-7",
        model_default="claude-sonnet-4-6",
    )
    runner = WorkflowRunner(AsyncAnthropic(api_key="dummy"), s)

    out_modify = await runner.run(WORKFLOW_CODE_MODIFY, {})
    assert out_modify["placeholder"] is True

    out_issue = await runner.run(WORKFLOW_LINEAR_ISSUE, {})
    assert out_issue["placeholder"] is True
