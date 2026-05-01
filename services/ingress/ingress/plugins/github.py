"""GitHub webhook channel parser.

Verifies HMAC-SHA256 signature, filters to PR events, and normalizes payload.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime

from agent_secretary_schemas import ChannelTarget, RawEvent, ResponseRouting
from fastapi import APIRouter, Header, HTTPException, Request

from ingress.logging import get_logger
from ingress.plugins._base import ChannelParser
from ingress.publisher import EventPublisher

log = get_logger("ingress.plugins.github")

_HANDLED_PR_ACTIONS = {"opened", "synchronize", "reopened"}


class GithubChannelParser(ChannelParser):
    name = "github"

    def __init__(self, webhook_secret: str | None, publisher: EventPublisher) -> None:
        self._secret = webhook_secret
        self._publisher = publisher

    def register_routes(self, router: APIRouter) -> None:
        @router.post("/public/channels/github/webhook")
        async def webhook(
            request: Request,
            x_github_event: str = Header(...),
            x_hub_signature_256: str | None = Header(None),
            x_github_delivery: str | None = Header(None),
        ) -> dict:
            body = await request.body()
            self._verify_signature(body, x_hub_signature_256)
            event = await self.parse(
                event_type=x_github_event,
                delivery_id=x_github_delivery,
                payload_bytes=body,
            )
            if event is None:
                log.info("github.webhook.skipped", event_type=x_github_event)
                return {"status": "skipped"}
            await self._publisher.publish(event)
            log.info(
                "github.webhook.published",
                event_id=event.event_id,
                event_type=x_github_event,
            )
            return {"status": "accepted", "event_id": event.event_id}

    def _verify_signature(self, body: bytes, signature_header: str | None) -> None:
        if not self._secret:
            log.warning("github.webhook.signature_disabled")
            return
        if not signature_header or not signature_header.startswith("sha256="):
            raise HTTPException(status_code=401, detail="missing or malformed signature")
        digest = hmac.new(self._secret.encode(), body, hashlib.sha256).hexdigest()
        expected = f"sha256={digest}"
        if not hmac.compare_digest(expected, signature_header):
            raise HTTPException(status_code=401, detail="invalid signature")

    async def parse(
        self,
        *,
        event_type: str,
        delivery_id: str | None,
        payload_bytes: bytes,
    ) -> RawEvent | None:
        import json

        if event_type == "ping":
            return None
        if event_type != "pull_request":
            log.info("github.webhook.unsupported_event", event_type=event_type)
            return None

        payload = json.loads(payload_bytes)
        action = payload.get("action")
        if action not in _HANDLED_PR_ACTIONS:
            return None

        pr = payload["pull_request"]
        if pr.get("draft"):
            return None

        repo = payload["repository"]
        normalized = {
            "trigger": f"pr_{action}",
            "repo": {
                "owner": repo["owner"]["login"],
                "name": repo["name"],
                "full_name": repo["full_name"],
            },
            "pr": {
                "number": pr["number"],
                "title": pr["title"],
                "description": pr.get("body") or "",
                "author": pr["user"]["login"],
                "head_sha": pr["head"]["sha"],
                "base_sha": pr["base"]["sha"],
                "url": pr["html_url"],
            },
            "installation_id": (payload.get("installation") or {}).get("id"),
        }

        response_routing = ResponseRouting(
            primary=ChannelTarget(
                channel="github",
                target={
                    "repo": repo["full_name"],
                    "pr_number": pr["number"],
                    "installation_id": normalized["installation_id"],
                },
            )
        )

        return RawEvent(
            event_id=delivery_id or str(uuid.uuid4()),
            source_channel="github",
            received_at=datetime.now(UTC),
            raw_payload=payload,
            normalized=normalized,
            response_routing=response_routing,
        )
