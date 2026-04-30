"""RawEvent → TaskSpec classifier.

PoC 단계: trigger 기반 단순 매핑.
  - PR webhook → pr_review 워크플로우
  - Slack mention/button → code_analyze / code_modify / linear_issue
    (워크플로우는 RawEvent.normalized.workflow 가 지정)

이벤트 1개 → task 1개 (1:1) 만 지원. 이후 task 그래프로 확장 가능.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from agent_secretary_config import ALL_WORKFLOWS, WORKFLOW_PR_REVIEW
from agent_secretary_schemas import RawEvent, TaskSpec


class UnclassifiedEvent(Exception):
    """Raised when an event does not match any known workflow."""


def classify(event: RawEvent) -> TaskSpec:
    trigger = event.normalized.get("trigger", "")

    # GitHub PR / CLI manual → PR review pipeline
    if trigger.startswith("pr_") or trigger == "manual":
        return _build_pr_review_task(event)

    # Slack mention / button → workflow specified in normalized payload
    if trigger in ("slack_mention", "slack_button"):
        workflow = event.normalized.get("workflow")
        if workflow not in ALL_WORKFLOWS:
            raise UnclassifiedEvent(f"unknown slack workflow: {workflow!r}")
        return _build_slack_task(event, workflow)

    raise UnclassifiedEvent(f"no workflow matches trigger={trigger!r}")


def _build_pr_review_task(event: RawEvent) -> TaskSpec:
    pr = event.normalized.get("pr", {})
    workflow_input = {
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
    return _make_task(event, WORKFLOW_PR_REVIEW, workflow_input)


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


def _make_task(event: RawEvent, workflow: str, workflow_input: dict) -> TaskSpec:
    return TaskSpec(
        task_id=_task_id(event.event_id, workflow),
        event_id=event.event_id,
        workflow=workflow,
        workflow_input=workflow_input,
        response_routing=event.response_routing,
        created_at=datetime.now(UTC),
    )


def _task_id(event_id: str, workflow: str) -> str:
    digest = hashlib.sha256(f"{event_id}:{workflow}".encode()).hexdigest()
    return digest[:32]
