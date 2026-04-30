"""CLI channel parser — manual dry-run trigger.

Accepts a structured JSON payload describing a PR (already-prepared diff and metadata),
useful for testing the pipeline without a real GitHub webhook.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from agent_secretary_schemas import ChannelTarget, RawEvent, ResponseRouting
from fastapi import APIRouter
from pydantic import BaseModel

from ingress.logging import get_logger
from ingress.plugins._base import ChannelParser
from ingress.publisher import EventPublisher

log = get_logger("ingress.plugins.cli")


class CliPrInput(BaseModel):
    title: str
    description: str = ""
    author: str = "cli-user"
    repo: str = "local/cli"
    pr_number: int = 0
    head_sha: str = "HEAD"
    base_sha: str = "BASE"
    changed_files: list[str]
    diff: str
    diff_stats: dict | None = None


class CliChannelParser(ChannelParser):
    name = "cli"

    def __init__(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    def register_routes(self, router: APIRouter) -> None:
        @router.post("/channels/cli/submit")
        async def submit(payload: CliPrInput) -> dict:
            event = await self.parse(payload=payload)
            await self._publisher.publish(event)
            log.info("cli.submit.published", event_id=event.event_id)
            return {"status": "accepted", "event_id": event.event_id}

    async def parse(self, *, payload: CliPrInput) -> RawEvent:
        normalized = {
            "trigger": "manual",
            "repo": {"full_name": payload.repo},
            "pr": {
                "number": payload.pr_number,
                "title": payload.title,
                "description": payload.description,
                "author": payload.author,
                "head_sha": payload.head_sha,
                "base_sha": payload.base_sha,
                "changed_files": payload.changed_files,
                "diff": payload.diff,
                "diff_stats": payload.diff_stats
                or {
                    "files_changed": len(payload.changed_files),
                    "additions": 0,
                    "deletions": 0,
                },
            },
        }
        return RawEvent(
            event_id=str(uuid.uuid4()),
            source_channel="cli",
            received_at=datetime.now(UTC),
            raw_payload=payload.model_dump(),
            normalized=normalized,
            response_routing=ResponseRouting(
                primary=ChannelTarget(channel="cli", target={"event_id_echo": True})
            ),
        )
