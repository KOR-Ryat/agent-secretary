"""Workflow dispatcher: maps TaskSpec.workflow → workflow runner."""

from __future__ import annotations

from agent_secretary_config import (
    GitHubAppAuth,
    WORKFLOW_CODE_ANALYZE,
    WORKFLOW_CODE_MODIFY,
    WORKFLOW_LINEAR_ISSUE,
    WORKFLOW_PR_REVIEW,
    WORKFLOW_PR_REVIEW_MONOLITHIC,
)

from agents.config import Settings
from agents.github_labels import ack_request
from agents.logging import get_logger
from agents.workflows.code_analyze import CodeAnalyzeRunner
from agents.workflows.monolithic_review import MonolithicReviewRunner
from agents.workflows.placeholder import PlaceholderRunner
from agents.workflows.pr_review import PrReviewRunner

log = get_logger("agents.runner")

_PLACEHOLDER_WORKFLOWS = {WORKFLOW_CODE_MODIFY, WORKFLOW_LINEAR_ISSUE}
_LABEL_TRIGGERS = {"label_request"}


class UnknownWorkflowError(Exception):
    pass


class WorkflowRunner:
    def __init__(self, settings: Settings) -> None:
        self._pr_review = PrReviewRunner(settings)
        self._monolithic = MonolithicReviewRunner(settings)
        self._code_analyze = CodeAnalyzeRunner(settings)
        self._placeholder = PlaceholderRunner()
        try:
            self._auth: GitHubAppAuth | None = GitHubAppAuth.from_env()
        except Exception:
            self._auth = None

    async def run(self, workflow: str, workflow_input: dict) -> dict:
        await self._ack_label(workflow_input)

        if workflow == WORKFLOW_PR_REVIEW:
            return await self._pr_review.run(workflow_input)
        if workflow == WORKFLOW_PR_REVIEW_MONOLITHIC:
            return await self._monolithic.run(workflow_input)
        if workflow == WORKFLOW_CODE_ANALYZE:
            return await self._code_analyze.run(workflow_input)
        if workflow in _PLACEHOLDER_WORKFLOWS:
            return await self._placeholder.run(workflow, workflow_input)
        raise UnknownWorkflowError(f"unknown workflow: {workflow}")

    async def _ack_label(self, workflow_input: dict) -> None:
        if workflow_input.get("trigger") not in _LABEL_TRIGGERS:
            return
        if not self._auth:
            log.warning("agents.runner.ack_label.no_auth")
            return
        repo = (workflow_input.get("repo") or {}).get("full_name")
        pr = workflow_input.get("pr") or workflow_input.get("issue") or {}
        number = pr.get("number")
        if not repo or not number:
            return
        try:
            await ack_request(self._auth, repo, number)
        except Exception as e:
            log.warning("agents.runner.ack_label.failed", repo=repo, number=number, error=str(e))
