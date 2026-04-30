"""Placeholder workflows for `code_modify` and `linear_issue`.

These are wired into the runner / classifier so the full Slack →
ingress → core → agents → egress pipeline is exercisable end-to-end,
but they return a fixed "🚧 not yet implemented" result instead of
invoking an LLM. Real implementations will replace these one at a time.
"""

from __future__ import annotations

from agent_secretary_config import WORKFLOW_CODE_MODIFY, WORKFLOW_LINEAR_ISSUE

from agents.logging import get_logger

log = get_logger("agents.workflows.placeholder")


_MESSAGES: dict[str, tuple[str, str]] = {
    # workflow id → (summary, detail or "")
    WORKFLOW_CODE_MODIFY: (
        "🚧 코드 수정 기능은 아직 구현 중입니다. "
        "우선 `분석` 으로 원인을 파악하시면 좋습니다.",
        (
            "# 🚧 코드 수정 (`code_modify`) — 구현 중\n\n"
            "이 워크플로우는 아직 구현되지 않았습니다.\n\n"
            "**대안**\n"
            "- `@bot 분석` — 버그 원인 분석\n"
            "- `@bot 이슈 등록` — Linear 이슈 등록 (placeholder)\n"
        ),
    ),
    WORKFLOW_LINEAR_ISSUE: (
        "🚧 Linear 자동 등록은 아직 구현 중입니다. "
        "당분간은 분석 결과를 수동으로 복사해 사용해 주세요.",
        (
            "# 🚧 Linear 이슈 등록 (`linear_issue`) — 구현 중\n\n"
            "이 워크플로우는 아직 구현되지 않았습니다.\n\n"
            "**대안**\n"
            "- `@bot 분석` 으로 분석 결과를 받아 본문으로 활용\n"
            "- Linear 에서 직접 이슈 생성\n"
        ),
    ),
}


class PlaceholderRunner:
    """Single runner used by both placeholder workflows.

    Returns a fixed `{summary, detail}` result without calling any LLM.
    """

    async def run(self, workflow: str, workflow_input: dict) -> dict:
        summary, detail = _MESSAGES.get(
            workflow,
            ("🚧 이 워크플로우는 아직 구현되지 않았습니다.", ""),
        )
        log.info(
            "workflow.placeholder.run",
            workflow=workflow,
            channel=workflow_input.get("channel_name"),
        )
        return {
            "summary_markdown": summary,
            "detail_markdown": detail or None,
            "placeholder": True,
            "workflow": workflow,
        }
