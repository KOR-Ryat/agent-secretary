"""GitHub label management helper for workflow ACK/completion signals."""

from __future__ import annotations

import httpx
from agent_secretary_config import GitHubAppAuth

from agents.logging import get_logger

log = get_logger("agents.github_labels")

LABEL_REQUEST_REVIEW = "agent:request-review"   # user adds this to trigger
LABEL_REQUEST_RECEIVED = "agent:request-received"  # bot sets this as ACK

_GITHUB_API = "https://api.github.com"
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "agent-secretary/0.0.0",
}


async def ack_request(auth: GitHubAppAuth, repo: str, number: int) -> None:
    """Swap agent:request-review → agent:request-received as workflow ACK."""
    token = await auth.get_token()
    headers = {**_HEADERS, "Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        await _ensure_label(client, headers, repo, LABEL_REQUEST_RECEIVED, "0075ca")
        await client.post(
            f"{_GITHUB_API}/repos/{repo}/issues/{number}/labels",
            headers=headers,
            json={"labels": [LABEL_REQUEST_RECEIVED]},
        )
        await client.request(
            "DELETE",
            f"{_GITHUB_API}/repos/{repo}/issues/{number}/labels/{LABEL_REQUEST_REVIEW}",
            headers=headers,
        )
    log.info("github_labels.acked", repo=repo, number=number)


async def remove_received_label(auth: GitHubAppAuth, repo: str, number: int) -> None:
    """Remove agent:request-received label after workflow completion."""
    token = await auth.get_token()
    headers = {**_HEADERS, "Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.request(
            "DELETE",
            f"{_GITHUB_API}/repos/{repo}/issues/{number}/labels/{LABEL_REQUEST_RECEIVED}",
            headers=headers,
        )
    if resp.status_code not in (200, 404):
        log.warning("github_labels.remove_failed", repo=repo, number=number, status=resp.status_code)
    else:
        log.info("github_labels.removed", repo=repo, number=number)


async def _ensure_label(
    client: httpx.AsyncClient, headers: dict, repo: str, name: str, color: str
) -> None:
    resp = await client.get(f"{_GITHUB_API}/repos/{repo}/labels/{name}", headers=headers)
    if resp.status_code == 404:
        await client.post(
            f"{_GITHUB_API}/repos/{repo}/labels",
            headers=headers,
            json={"name": name, "color": color},
        )
