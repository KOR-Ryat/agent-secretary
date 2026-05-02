"""RawEvent → list[TaskSpec] classifier.

PoC 단계: trigger 기반 단순 매핑.
  - PR webhook → pr_review (+ pr_review_monolithic shadow when ab_mode)
  - Slack mention/button → code_analyze / code_modify / linear_issue
    (워크플로우는 RawEvent.normalized.workflow 가 지정)

대부분의 이벤트는 task 1개. PR 리뷰 + ab 모드일 때만 task 2개 (정상 + shadow).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from agent_secretary_config import (
    ALL_WORKFLOWS,
    GITHUB_AUTO_PR_TRIGGERS,
    GITHUB_TRIGGER_TO_WORKFLOW,
    WORKFLOW_PR_REVIEW,
    WORKFLOW_PR_REVIEW_MONOLITHIC,
)
from agent_secretary_schemas import RawEvent, TaskSpec


class UnclassifiedEvent(Exception):
    """Raised when an event does not match any known workflow."""


def classify(event: RawEvent, *, ab_mode: bool = False) -> list[TaskSpec]:
    trigger = event.normalized.get("trigger", "")

    # GitHub PR auto triggers (configurable) or explicit label/comment request
    if trigger in GITHUB_AUTO_PR_TRIGGERS or trigger in GITHUB_TRIGGER_TO_WORKFLOW or trigger == "manual":
        tasks = [_build_pr_review_task(event)]
        if ab_mode:
            tasks.append(_build_pr_review_monolithic_shadow(event))
        return tasks

    # Slack mention / button → workflow specified in normalized payload
    if trigger in ("slack_mention", "slack_button"):
        workflow = event.normalized.get("workflow")
        if workflow not in ALL_WORKFLOWS:
            raise UnclassifiedEvent(f"unknown slack workflow: {workflow!r}")
        return [_build_slack_task(event, workflow)]

    raise UnclassifiedEvent(f"no workflow matches trigger={trigger!r}")


def _build_pr_review_task(event: RawEvent) -> TaskSpec:
    return _make_task(event, WORKFLOW_PR_REVIEW, _pr_review_input(event))


def _build_pr_review_monolithic_shadow(event: RawEvent) -> TaskSpec:
    """A/B Case B — same input as A, but shadow=True so the result
    lands in pr_trace without being published to egress."""
    return _make_task(
        event,
        WORKFLOW_PR_REVIEW_MONOLITHIC,
        _pr_review_input(event),
        shadow=True,
    )


def _pr_review_input(event: RawEvent) -> dict:
    pr = event.normalized.get("pr", {})
    return {
        "pr": {
            "title": pr.get("title", ""),
            "description": pr.get("description", ""),
            "author": pr.get("author", ""),
            "changed_files": pr.get("changed_files", []),
            "diff_stats": pr.get("diff_stats", {}),
            "diff": pr.get("diff", ""),
            "head_sha": pr.get("head_sha"),
            "base_sha": pr.get("base_sha"),
            "url": pr.get("url"),
        },
        "repo": event.normalized.get("repo", {}),
    }


def _build_slack_task(event: RawEvent, workflow: str) -> TaskSpec:
    n = event.normalized
    workflow_input = {
        "service_resolution": n.get("service_resolution") or {},
        "channel_id": n.get("channel_id"),
        "channel_name": n.get("channel_name"),
        "thread_ts": n.get("thread_ts"),
        "mention_ts": n.get("mention_ts"),
        "user": n.get("user"),
        "text": n.get("text") or "",
        "thread_messages": n.get("thread_messages") or [],
    }
    return _make_task(event, workflow, workflow_input)


def _make_task(
    event: RawEvent,
    workflow: str,
    workflow_input: dict,
    *,
    shadow: bool = False,
) -> TaskSpec:
    return TaskSpec(
        task_id=_task_id(event.event_id, workflow),
        event_id=event.event_id,
        workflow=workflow,
        workflow_input=workflow_input,
        response_routing=event.response_routing,
        created_at=datetime.now(UTC),
        shadow=shadow,
    )


def _task_id(event_id: str, workflow: str) -> str:
    digest = hashlib.sha256(f"{event_id}:{workflow}".encode()).hexdigest()
    return digest[:32]
