"""GitHub PR comment deliverer.

Reads `response_routing.primary.target` for `repo` and `pr_number`, posts
the result's `summary_markdown` as an issue comment using the GitHub REST API.

Phase 1 (shadow mode): comments only — no merge, label, or status changes.
"""

from __future__ import annotations

import httpx
from agent_secretary_schemas import ResultEvent

from egress.logging import get_logger
from egress.plugins._base import ChannelDeliverer

log = get_logger("egress.plugins.github")


class GithubDeliverer(ChannelDeliverer):
    name = "github"

    def __init__(self, token: str | None) -> None:
        self._token = token
        self._client = httpx.AsyncClient(
            base_url="https://api.github.com",
            timeout=httpx.Timeout(15.0),
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "agent-secretary/0.0.0",
            },
        )

    async def deliver(self, result: ResultEvent) -> None:
        target = result.response_routing.primary.target
        repo = target.get("repo")
        pr_number = target.get("pr_number")
        if not repo or not pr_number:
            log.warning(
                "github.deliver.missing_target",
                repo=repo,
                pr_number=pr_number,
                result_id=result.result_id,
            )
            return

        if not self._token:
            log.warning(
                "github.deliver.no_token",
                repo=repo,
                pr_number=pr_number,
                hint="set GITHUB_TOKEN; skipping actual POST",
            )
            return

        url = f"/repos/{repo}/issues/{pr_number}/comments"
        response = await self._client.post(
            url,
            json={"body": result.summary_markdown},
            headers={"Authorization": f"Bearer {self._token}"},
        )
        response.raise_for_status()
        log.info(
            "github.deliver.posted",
            repo=repo,
            pr_number=pr_number,
            result_id=result.result_id,
            comment_id=response.json().get("id"),
        )

    async def close(self) -> None:
        await self._client.aclose()
