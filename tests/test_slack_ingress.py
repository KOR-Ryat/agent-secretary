"""Slack ingress plugin tests.

Verifies classification + RawEvent normalization shape.
Socket Mode integration is exercised by manual / e2e runs only — no
network call here.
"""

from __future__ import annotations

import pytest
from agent_secretary_config import (
    WORKFLOW_CODE_ANALYZE,
    WORKFLOW_CODE_MODIFY,
    WORKFLOW_LINEAR_ISSUE,
    classify_slack_text,
)


def test_classify_slack_text_keyword_matches():
    assert classify_slack_text("디버깅 좀 부탁") == WORKFLOW_CODE_ANALYZE
    assert classify_slack_text("이 PR 분석해줘") == WORKFLOW_CODE_ANALYZE
    assert classify_slack_text("이거 수정해줘") == WORKFLOW_CODE_MODIFY
    assert classify_slack_text("픽스 해줘") == WORKFLOW_CODE_MODIFY


def test_classify_slack_text_compound_keywords():
    """`이슈 등록` requires both words to appear."""
    assert classify_slack_text("이슈 등록 부탁") == WORKFLOW_LINEAR_ISSUE
    # "이슈" alone should not match (less specific than 분석/수정)
    assert classify_slack_text("이슈가 있어요") is None


def test_classify_slack_text_no_match():
    assert classify_slack_text("안녕") is None
    assert classify_slack_text("") is None
    assert classify_slack_text("도와주세요") is None


def test_classify_slack_text_specificity_order():
    """`이슈 등록` is checked before `이슈` alone."""
    assert classify_slack_text("이슈 등록해줘") == WORKFLOW_LINEAR_ISSUE


def test_build_event_normalizes_known_channel():
    """Known service channel resolves; RawEvent carries service + repos."""
    from ingress.plugins.slack import SlackChannelParser

    # Construct without starting Socket Mode — just exercise _build_event.
    parser = SlackChannelParser.__new__(SlackChannelParser)

    event = parser._build_event(
        workflow=WORKFLOW_CODE_ANALYZE,
        trigger="slack_mention",
        channel_id="C099XH6QR97",          # if-payment-production
        thread_ts="1700000000.000100",
        mention_ts="1700000000.000200",
        user="UABC",
        text="버그 분석해줘",
        thread_messages=[{"user": "UDEF", "text": "에러 발생함", "ts": "1700000000.000050"}],
    )

    assert event.source_channel == "slack"
    assert event.normalized["trigger"] == "slack_mention"
    assert event.normalized["workflow"] == WORKFLOW_CODE_ANALYZE
    assert event.normalized["channel_id"] == "C099XH6QR97"
    assert event.normalized["channel_name"] == "if-payment-production"
    assert event.normalized["service_resolution"]["service"] == "if"
    assert event.normalized["service_resolution"]["env"] == "production"
    repo_names = [r["name"] for r in event.normalized["service_resolution"]["repos"]]
    assert "mesher-labs/project-201-server" in repo_names

    # Response routing carries timestamps so egress can react/post in-thread.
    assert event.response_routing.primary.channel == "slack"
    assert event.response_routing.primary.target["channel_id"] == "C099XH6QR97"
    assert event.response_routing.primary.target["thread_ts"] == "1700000000.000100"
    assert event.response_routing.primary.target["mention_ts"] == "1700000000.000200"


def test_build_event_unbound_channel_falls_back():
    from ingress.plugins.slack import SlackChannelParser

    parser = SlackChannelParser.__new__(SlackChannelParser)

    event = parser._build_event(
        workflow=WORKFLOW_CODE_ANALYZE,
        trigger="slack_button",
        channel_id="CXYZUNKNOWN",
        thread_ts=None,
        mention_ts=None,
        user="UABC",
        text="",
        thread_messages=[],
    )

    assert event.normalized["service_resolution"]["service"] is None
    assert event.normalized["service_resolution"]["env"] is None
    assert event.normalized["service_resolution"]["repos"] == []
    # Unbound channel → fallback to raw ID for the human-readable name.
    assert event.normalized["channel_name"] == "CXYZUNKNOWN"


# --- _on_mention / _on_interactive flows ----------------------------------


def _make_parser_with_mocks():
    """Build a SlackChannelParser without invoking the real Socket Mode +
    Web Client constructors. Replaces `_web` and `_publisher` with mocks."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ingress.plugins.slack import SlackChannelParser

    parser = SlackChannelParser.__new__(SlackChannelParser)
    parser._publisher = AsyncMock()
    parser._web = SimpleNamespace(
        chat_postMessage=AsyncMock(),
        chat_delete=AsyncMock(),
        conversations_replies=AsyncMock(
            return_value={
                "messages": [
                    {"user": "UABC", "text": "context msg", "ts": "1700000000.000050"},
                ]
            }
        ),
        reactions_add=AsyncMock(),
    )
    return parser


def _mention_event(*, text: str = "분석 좀") -> dict:
    return {
        "channel": "C099XH6QR97",  # if-payment-production (registered)
        "ts": "1700000000.000200",
        "thread_ts": "1700000000.000100",
        "user": "UABC",
        "text": f"<@U99BOT> {text}",
    }


@pytest.mark.asyncio
async def test_on_mention_keyword_publishes_and_reacts_with_hourglass():
    parser = _make_parser_with_mocks()
    await parser._on_mention(_mention_event(text="분석 좀 해줘"))

    # Published the RawEvent.
    parser._publisher.publish.assert_awaited_once()
    event = parser._publisher.publish.await_args.args[0]
    assert event.normalized["workflow"] == "code_analyze"
    assert event.normalized["channel_id"] == "C099XH6QR97"
    # Mention text stripped of <@U...> prefix.
    assert event.normalized["text"] == "분석 좀 해줘"
    # Thread context fetched + included.
    assert len(event.normalized["thread_messages"]) == 1
    assert event.normalized["thread_messages"][0]["text"] == "context msg"

    # In-progress reaction added on the original mention timestamp.
    parser._web.reactions_add.assert_awaited_once_with(
        channel="C099XH6QR97",
        timestamp="1700000000.000200",
        name="hourglass_flowing_sand",
    )
    # No button block.
    parser._web.chat_postMessage.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_mention_empty_posts_button_block_no_publish():
    parser = _make_parser_with_mocks()
    await parser._on_mention(_mention_event(text=""))

    # No publish, no reaction (the user hasn't picked a command yet).
    parser._publisher.publish.assert_not_awaited()
    parser._web.reactions_add.assert_not_awaited()

    # Button block posted in-thread.
    parser._web.chat_postMessage.assert_awaited_once()
    posted = parser._web.chat_postMessage.await_args.kwargs
    assert posted["channel"] == "C099XH6QR97"
    assert posted["thread_ts"] == "1700000000.000100"
    blocks = posted["blocks"]
    assert blocks[0]["type"] == "actions"
    action_ids = [el["action_id"] for el in blocks[0]["elements"]]
    assert action_ids == ["cmd_debug", "cmd_fix", "cmd_issue"]


@pytest.mark.asyncio
async def test_on_mention_unmatched_text_posts_button_block():
    """Text without recognized keywords → buttons (don't try to guess)."""
    parser = _make_parser_with_mocks()
    await parser._on_mention(_mention_event(text="안녕하세요 봇아"))

    parser._publisher.publish.assert_not_awaited()
    parser._web.chat_postMessage.assert_awaited_once()


def _interactive_payload(action_id: str, *, malformed_block_id: bool = False) -> dict:
    import json

    block_id = (
        "not-json"
        if malformed_block_id
        else json.dumps(
            {
                "channel": "C099XH6QR97",
                "thread_ts": "1700000000.000100",
                "mention_ts": "1700000000.000200",
            }
        )
    )
    return {
        "actions": [{"action_id": action_id, "block_id": block_id}],
        "container": {"message_ts": "1700000000.000300"},
        "user": {"id": "UABC"},
    }


@pytest.mark.asyncio
async def test_on_interactive_button_click_publishes_and_deletes_block():
    parser = _make_parser_with_mocks()
    await parser._on_interactive(_interactive_payload("cmd_debug"))

    # Button block deleted (it's served its purpose).
    parser._web.chat_delete.assert_awaited_once_with(
        channel="C099XH6QR97", ts="1700000000.000300"
    )

    # Workflow resolved + published.
    parser._publisher.publish.assert_awaited_once()
    event = parser._publisher.publish.await_args.args[0]
    assert event.normalized["workflow"] == "code_analyze"
    assert event.normalized["trigger"] == "slack_button"
    # Mention timestamp preserved (egress reacts on this).
    assert event.normalized["mention_ts"] == "1700000000.000200"

    # Hourglass on the original mention.
    parser._web.reactions_add.assert_awaited_once_with(
        channel="C099XH6QR97",
        timestamp="1700000000.000200",
        name="hourglass_flowing_sand",
    )


@pytest.mark.asyncio
async def test_on_interactive_unknown_action_does_nothing():
    parser = _make_parser_with_mocks()
    await parser._on_interactive(_interactive_payload("cmd_made_up"))
    parser._publisher.publish.assert_not_awaited()
    parser._web.chat_delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_interactive_malformed_block_id_does_not_publish():
    parser = _make_parser_with_mocks()
    await parser._on_interactive(
        _interactive_payload("cmd_debug", malformed_block_id=True)
    )
    parser._publisher.publish.assert_not_awaited()
    # block_id parsing failed before chat_delete; no delete attempted either.
    parser._web.chat_delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_thread_returns_empty_when_api_fails():
    """Thread fetch failure shouldn't crash the mention handler."""
    from unittest.mock import AsyncMock

    parser = _make_parser_with_mocks()
    parser._web.conversations_replies = AsyncMock(side_effect=RuntimeError("net fail"))

    result = await parser._fetch_thread("C99", "1700000000.000100")
    assert result == []

