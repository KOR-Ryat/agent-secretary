"""Slack ingress plugin tests.

Verifies classification + RawEvent normalization shape.
Socket Mode integration is exercised by manual / e2e runs only — no
network call here.
"""

from __future__ import annotations

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
