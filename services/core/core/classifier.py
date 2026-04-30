"""RawEvent → TaskSpec classifier.

PoC 단계: trigger 기반 단순 매핑. PR 이벤트 → pr_review 워크플로우.
이벤트 1개 → task 1개 (1:1) 만 지원. 이후 task 그래프로 확장 가능.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from agent_secretary_config import WORKFLOW_PR_REVIEW
from agent_secretary_schemas import RawEvent, TaskSpec


class UnclassifiedEvent(Exception):
    """Raised when an event does not match any known workflow."""


def classify(event: RawEvent) -> TaskSpec:
    trigger = event.normalized.get("trigger", "")
    if trigger.startswith("pr_") or trigger == "manual":
        return _build_pr_review_task(event)
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
    task_id = _task_id(event.event_id, WORKFLOW_PR_REVIEW)
    return TaskSpec(
        task_id=task_id,
        event_id=event.event_id,
        workflow=WORKFLOW_PR_REVIEW,
        workflow_input=workflow_input,
        response_routing=event.response_routing,
        created_at=datetime.now(UTC),
    )


def _task_id(event_id: str, workflow: str) -> str:
    digest = hashlib.sha256(f"{event_id}:{workflow}".encode()).hexdigest()
    return digest[:32]
