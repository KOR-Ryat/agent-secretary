"""Workflow identifiers used in TaskSpec.workflow.

Core's classifier emits these; agents' runner dispatches on them. Both
sides import from here so the strings can never drift.
"""

# Existing PR review pipeline (dispatcher → personas → CTO).
WORKFLOW_PR_REVIEW = "pr_review"

# Slack-driven, single-agent workflows (ported from legacy debug/fix/issue).
WORKFLOW_CODE_ANALYZE = "code_analyze"   # legacy: debug
WORKFLOW_CODE_MODIFY = "code_modify"     # legacy: fix (placeholder)
WORKFLOW_LINEAR_ISSUE = "linear_issue"   # legacy: issue (placeholder)

ALL_WORKFLOWS: tuple[str, ...] = (
    WORKFLOW_PR_REVIEW,
    WORKFLOW_CODE_ANALYZE,
    WORKFLOW_CODE_MODIFY,
    WORKFLOW_LINEAR_ISSUE,
)


# --- Slack mention keyword → workflow mapping ---------------------------
#
# Used by the Slack ingress plugin to classify @mention text. Matched
# against the mention's text (case-insensitive). Each entry is a tuple of
# *all* substrings that must be present, plus the workflow they map to.
# First match wins — order entries from most-specific to least-specific.
SLACK_KEYWORD_TO_WORKFLOW: tuple[tuple[tuple[str, ...], str], ...] = (
    (("이슈", "등록"), WORKFLOW_LINEAR_ISSUE),   # 두 단어 모두 포함
    (("디버깅",), WORKFLOW_CODE_ANALYZE),
    (("분석",), WORKFLOW_CODE_ANALYZE),
    (("수정",), WORKFLOW_CODE_MODIFY),
    (("픽스",), WORKFLOW_CODE_MODIFY),
)


def classify_slack_text(text: str) -> str | None:
    """Return the workflow id matching a Slack @mention text, or None."""
    if not text:
        return None
    haystack = text.lower()
    for keywords, workflow in SLACK_KEYWORD_TO_WORKFLOW:
        if all(k.lower() in haystack for k in keywords):
            return workflow
    return None
