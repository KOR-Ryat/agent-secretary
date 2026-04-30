"""Workflow dispatcher: maps TaskSpec.workflow → workflow runner."""

from __future__ import annotations

from agent_secretary_config import (
    WORKFLOW_CODE_ANALYZE,
    WORKFLOW_CODE_MODIFY,
    WORKFLOW_LINEAR_ISSUE,
    WORKFLOW_PR_REVIEW,
)
from anthropic import AsyncAnthropic

from agents.config import Settings
from agents.workflows.code_analyze import CodeAnalyzeRunner
from agents.workflows.placeholder import PlaceholderRunner
from agents.workflows.pr_review import PrReviewRunner

_PLACEHOLDER_WORKFLOWS = {WORKFLOW_CODE_MODIFY, WORKFLOW_LINEAR_ISSUE}


class UnknownWorkflowError(Exception):
    pass


class WorkflowRunner:
    def __init__(self, client: AsyncAnthropic, settings: Settings) -> None:
        self._pr_review = PrReviewRunner(client, settings)
        self._code_analyze = CodeAnalyzeRunner(settings)
        self._placeholder = PlaceholderRunner()

    async def run(self, workflow: str, workflow_input: dict) -> dict:
        if workflow == WORKFLOW_PR_REVIEW:
            return await self._pr_review.run(workflow_input)
        if workflow == WORKFLOW_CODE_ANALYZE:
            return await self._code_analyze.run(workflow_input)
        if workflow in _PLACEHOLDER_WORKFLOWS:
            return await self._placeholder.run(workflow, workflow_input)
        raise UnknownWorkflowError(f"unknown workflow: {workflow}")
