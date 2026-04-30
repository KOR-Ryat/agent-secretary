"""code_analyze workflow tests.

Mocks `claude_agent_sdk.query` and the workspace mount so the test
exercises the prompt assembly, output parsing, and result shape without
a real LLM call or real worktree.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from agent_secretary_config import (
    WORKFLOW_CODE_ANALYZE,
)

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


def _slack_workflow_input() -> dict:
    return {
        "service_resolution": {
            "service": "if",
            "env": "production",
            "repos": [
                {
                    "name": "mesher-labs/project-201-server",
                    "production": "main",
                    "staging": "stage",
                    "dev": "dev",
                },
            ],
        },
        "channel_id": "C099XH6QR97",
        "channel_name": "if-payment-production",
        "thread_ts": "1700000000.000100",
        "mention_ts": "1700000000.000200",
        "user": "UABC",
        "text": "결제 에러 분석해줘",
        "thread_messages": [
            {"user": "UABC", "text": "결제 502 발생", "ts": "1700000000.000050"},
        ],
    }


@pytest.mark.asyncio
async def test_code_analyze_returns_summary_and_detail(monkeypatch, tmp_path):
    """Happy path: agent returns 메시지/파일, workflow extracts both."""
    os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("AGENT_WORKSPACE_DIR", str(tmp_path / "ws"))

    from agents.skills.workspace import WorkspaceManager
    from agents.workflows import code_analyze as ca

    # Stub WorkspaceManager.mount to a no-op context manager that yields a tmp path.
    @asynccontextmanager
    async def fake_mount(self, repo, branch, session_id, *, fetch_first=True):
        path = tmp_path / f"{repo.short_name}--{branch}"
        path.mkdir(parents=True, exist_ok=True)
        yield path

    monkeypatch.setattr(WorkspaceManager, "mount", fake_mount)

    # Stub claude_agent_sdk.query to yield a canned ResultMessage.
    canned_text = (
        "분석 완료.\n\n"
        "```json\n"
        '{"메시지":"502 의 원인은 GeminiAdapter 의 content-filter 응답 처리 누락.",'
        '"파일":"# 결제 502 분석\\n\\n## 원인\\n..."}'
        "\n```"
    )

    # Swap `ResultMessage` used in code_analyze.py for our fake type so the
    # isinstance check matches and the workflow extracts `.result`.
    monkeypatch.setattr(ca, "ResultMessage", _FakeResultMessage)

    async def fake_query(*, prompt, options, transport=None):
        yield _FakeResultMessage(canned_text)

    monkeypatch.setattr(ca, "query", fake_query)

    runner = ca.CodeAnalyzeRunner(_settings(PROMPTS_DIR))
    result = await runner.run(_slack_workflow_input())

    assert result["summary_markdown"].startswith("502 의 원인")
    assert result["detail_markdown"].startswith("# 결제 502 분석")
    assert result["service"] == "if"
    assert result["env"] == "production"
    assert result["mounted_repos"][0]["name"] == "mesher-labs/project-201-server"
    assert result["mounted_repos"][0]["branch"] == "main"


class _FakeResultMessage:
    """Stand-in for the SDK's ResultMessage; carries `.result` text."""

    def __init__(self, result: str) -> None:
        self.result = result


@pytest.mark.asyncio
async def test_code_analyze_no_service_returns_error(monkeypatch, tmp_path):
    os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("AGENT_WORKSPACE_DIR", str(tmp_path / "ws"))

    from agents.workflows import code_analyze as ca

    runner = ca.CodeAnalyzeRunner(_settings(PROMPTS_DIR))
    result = await runner.run(
        {
            "service_resolution": {"service": None, "env": None, "repos": []},
            "channel_name": "general---공지",
            "text": "분석",
            "thread_messages": [],
        }
    )

    assert "error" in result
    assert result["summary_markdown"].startswith("❌")


def test_classifier_routes_slack_mention_to_code_analyze():
    """Core classifier accepts a Slack RawEvent with workflow=code_analyze."""
    from datetime import UTC, datetime

    from agent_secretary_schemas import ChannelTarget, RawEvent, ResponseRouting
    from core.classifier import classify

    event = RawEvent(
        event_id="e1",
        source_channel="slack",
        received_at=datetime.now(UTC),
        raw_payload={},
        normalized={
            "trigger": "slack_mention",
            "workflow": WORKFLOW_CODE_ANALYZE,
            "channel_id": "C99",
            "channel_name": "x",
            "thread_ts": "1.000",
            "mention_ts": "1.001",
            "user": "U",
            "text": "분석 ㄱㄱ",
            "thread_messages": [],
            "service_resolution": {"service": "viv", "env": "production", "repos": []},
        },
        response_routing=ResponseRouting(
            primary=ChannelTarget(channel="slack", target={"channel_id": "C99"})
        ),
    )

    task = classify(event)
    assert task.workflow == WORKFLOW_CODE_ANALYZE
    assert task.workflow_input["channel_id"] == "C99"
    assert task.workflow_input["service_resolution"]["service"] == "viv"
    assert task.workflow_input["text"] == "분석 ㄱㄱ"


def test_classifier_rejects_unknown_slack_workflow():
    from datetime import UTC, datetime

    from agent_secretary_schemas import ChannelTarget, RawEvent, ResponseRouting
    from core.classifier import UnclassifiedEvent, classify

    event = RawEvent(
        event_id="e2",
        source_channel="slack",
        received_at=datetime.now(UTC),
        raw_payload={},
        normalized={"trigger": "slack_mention", "workflow": "no_such_workflow"},
        response_routing=ResponseRouting(
            primary=ChannelTarget(channel="slack", target={})
        ),
    )
    with pytest.raises(UnclassifiedEvent):
        classify(event)
