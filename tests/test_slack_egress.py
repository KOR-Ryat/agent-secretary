"""Slack egress (SlackDeliverer) tests with a mocked WebClient."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent_secretary_schemas import ChannelTarget, ResponseRouting, ResultEvent


def _build_result(
    *,
    summary: str = "ok",
    detail: str | None = None,
    trace_url: str | None = None,
    error: bool = False,
) -> ResultEvent:
    return ResultEvent(
        result_id=str(uuid.uuid4()),
        task_id="task1",
        event_id="evt1",
        workflow="code_analyze",
        output={"error": "boom"} if error else {"foo": "bar"},
        summary_markdown=summary,
        detail_markdown=detail,
        trace_url=trace_url,
        response_routing=ResponseRouting(
            primary=ChannelTarget(
                channel="slack",
                target={
                    "channel_id": "C99",
                    "thread_ts": "1700000000.000100",
                    "mention_ts": "1700000000.000200",
                },
            )
        ),
        completed_at=datetime.now(UTC),
    )


def _mock_web():
    return SimpleNamespace(
        reactions_add=AsyncMock(),
        reactions_remove=AsyncMock(),
        chat_postMessage=AsyncMock(),
        close=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_deliver_summary_only_when_no_trace_url():
    from egress.plugins.slack import SlackDeliverer

    d = SlackDeliverer(bot_token="x")
    web = _mock_web()
    d._web = web  # type: ignore[assignment]

    await d.deliver(_build_result(summary="요약 메시지"))

    web.reactions_remove.assert_awaited_once_with(
        channel="C99", timestamp="1700000000.000200", name="hourglass_flowing_sand"
    )
    web.reactions_add.assert_awaited_once_with(
        channel="C99", timestamp="1700000000.000200", name="white_check_mark"
    )
    posted = web.chat_postMessage.await_args.kwargs
    assert posted["channel"] == "C99"
    assert posted["thread_ts"] == "1700000000.000100"
    assert posted["text"] == "요약 메시지"
    # No URL line appended.
    assert "Full report" not in posted["text"]


@pytest.mark.asyncio
async def test_deliver_appends_report_url_when_present():
    from egress.plugins.slack import SlackDeliverer

    d = SlackDeliverer(bot_token="x")
    web = _mock_web()
    d._web = web  # type: ignore[assignment]

    await d.deliver(
        _build_result(
            summary="짧은 요약",
            detail="# 상세 보고서",  # detail still flows to trace store; not posted as file
            trace_url="https://example.test/static/reports/task1",
        )
    )

    posted = web.chat_postMessage.await_args.kwargs
    assert "짧은 요약" in posted["text"]
    assert "https://example.test/static/reports/task1" in posted["text"]
    # Slack mrkdwn link syntax.
    assert "<https://example.test/static/reports/task1|Full report>" in posted["text"]


@pytest.mark.asyncio
async def test_deliver_no_file_upload_attempted():
    """The file upload code path is gone; reports go via URL only."""
    from egress.plugins import slack as slack_module
    from egress.plugins.slack import SlackDeliverer

    d = SlackDeliverer(bot_token="x")
    web = _mock_web()
    d._web = web  # type: ignore[assignment]

    await d.deliver(_build_result(detail="big detail"))

    # No files_upload_v2 method should be referenced anywhere in deliver
    # path. (Simple module-attribute check + AsyncMock that would fail
    # if it were used.)
    assert not hasattr(web, "files_upload_v2")
    assert "files_upload_v2" not in slack_module.SlackDeliverer.deliver.__code__.co_names


@pytest.mark.asyncio
async def test_deliver_error_uses_x_reaction():
    from egress.plugins.slack import SlackDeliverer

    d = SlackDeliverer(bot_token="x")
    web = _mock_web()
    d._web = web  # type: ignore[assignment]

    await d.deliver(_build_result(error=True))

    web.reactions_add.assert_awaited_once_with(
        channel="C99", timestamp="1700000000.000200", name="x"
    )


@pytest.mark.asyncio
async def test_deliver_no_token_skips():
    from egress.plugins.slack import SlackDeliverer

    d = SlackDeliverer(bot_token=None)
    # Should not throw; just logs and returns.
    await d.deliver(_build_result())


@pytest.mark.asyncio
async def test_deliver_missing_channel_skips():
    from egress.plugins.slack import SlackDeliverer

    d = SlackDeliverer(bot_token="x")
    web = _mock_web()
    d._web = web  # type: ignore[assignment]

    res = _build_result()
    # Force missing channel_id.
    res = res.model_copy(
        update={
            "response_routing": ResponseRouting(
                primary=ChannelTarget(channel="slack", target={})
            )
        }
    )

    await d.deliver(res)
    web.chat_postMessage.assert_not_awaited()
    web.reactions_add.assert_not_awaited()
