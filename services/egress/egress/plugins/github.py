"""GitHub PR comment deliverer.

Reads `response_routing.primary.target` for `repo` and `pr_number`, posts
the result's `summary_markdown` as an issue comment using the GitHub REST API.
For label-triggered workflows, removes agent:request-review after posting.
"""

from __future__ import annotations

import httpx
from agent_secretary_config import GitHubAppAuth
from agent_secretary_schemas import ResultEvent

from egress.logging import get_logger
from egress.plugins._base import ChannelDeliverer

log = get_logger("egress.plugins.github")


class GithubDeliverer(ChannelDeliverer):
    name = "github"

    def __init__(self, auth: GitHubAppAuth | None) -> None:
        self._auth = auth
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

        if not self._auth:
            log.warning(
                "github.deliver.no_auth",
                repo=repo,
                pr_number=pr_number,
                hint="set GITHUB_APP_ID / GITHUB_APP_INSTALLATION_ID / GITHUB_APP_PRIVATE_KEY",
            )
            return

        token = await self._auth.get_token()
        url = f"/repos/{repo}/issues/{pr_number}/comments"
        response = await self._client.post(
            url,
            json={"body": result.summary_markdown},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        log.info(
            "github.deliver.posted",
            repo=repo,
            pr_number=pr_number,
            result_id=result.result_id,
            comment_id=response.json().get("id"),
        )

        await self._remove_review_label(token, repo, pr_number)

    async def _remove_review_label(self, token: str, repo: str, number: int) -> None:
        label = "agent:request-received"
        resp = await self._client.request(
            "DELETE",
            f"/repos/{repo}/issues/{number}/labels/{label}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code not in (200, 404):
            log.warning(
                "github.deliver.label_remove_failed",
                repo=repo,
                number=number,
                status=resp.status_code,
            )
        else:
            log.info("github.deliver.label_removed", repo=repo, number=number)

    async def close(self) -> None:
        await self._client.aclose()
