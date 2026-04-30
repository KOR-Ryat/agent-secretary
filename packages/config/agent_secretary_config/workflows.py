"""Workflow identifiers used in TaskSpec.workflow.

Core's classifier emits these; agents' runner dispatches on them. Both
sides import from here so the strings can never drift.
"""

WORKFLOW_PR_REVIEW = "pr_review"

ALL_WORKFLOWS: tuple[str, ...] = (WORKFLOW_PR_REVIEW,)
