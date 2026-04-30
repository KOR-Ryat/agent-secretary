"""Workflow dispatcher: maps TaskSpec.workflow → workflow runner."""

from __future__ import annotations

from agent_secretary_config import WORKFLOW_PR_REVIEW
from anthropic import AsyncAnthropic

from agents.config import Settings
from agents.workflows.pr_review import PrReviewRunner


class UnknownWorkflowError(Exception):
    pass


class WorkflowRunner:
    def __init__(self, client: AsyncAnthropic, settings: Settings) -> None:
        self._pr_review = PrReviewRunner(client, settings)

    async def run(self, workflow: str, workflow_input: dict) -> dict:
        if workflow == WORKFLOW_PR_REVIEW:
            return await self._pr_review.run(workflow_input)
        raise UnknownWorkflowError(f"unknown workflow: {workflow}")
