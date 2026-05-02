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

_LABEL_REQUEST = "agent:request-review"
_LABEL_PREVENT = "agent:prevent-request"
_AUTO_PR_ACTIONS = {"opened", "synchronize", "reopened"}


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

        payload = json.loads(payload_bytes)
        action = payload.get("action")

        if event_type == "pull_request" and action in _AUTO_PR_ACTIONS:
            return self._parse_pr_auto(payload, delivery_id)
        if event_type == "pull_request" and action == "labeled":
            return self._parse_pr_label(payload, delivery_id)
        if event_type == "issues" and action == "labeled":
            return self._parse_issue_label(payload, delivery_id)
        if event_type == "issue_comment" and action == "created":
            return self._parse_comment_trigger(payload, delivery_id)

        log.info("github.webhook.unsupported_event", event_type=event_type, action=action)
        return None

    def _parse_pr_auto(self, payload: dict, delivery_id: str | None) -> RawEvent | None:
        pr = payload["pull_request"]
        if pr.get("draft"):
            return None

        labels = {lbl["name"] for lbl in (pr.get("labels") or [])}
        if _LABEL_PREVENT in labels:
            log.info("github.webhook.auto_pr.prevented", pr=pr["number"])
            return None

        repo = payload["repository"]
        installation_id = (payload.get("installation") or {}).get("id")
        action = payload.get("action")
        normalized = {
            "trigger": "auto_pr",
            "subject": "pr",
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
            "installation_id": installation_id,
        }
        log.info("github.webhook.auto_pr", pr=pr["number"], action=action)
        return RawEvent(
            event_id=delivery_id or str(uuid.uuid4()),
            source_channel="github",
            received_at=datetime.now(UTC),
            raw_payload=payload,
            normalized=normalized,
            response_routing=ResponseRouting(
                primary=ChannelTarget(
                    channel="github",
                    target={
                        "repo": repo["full_name"],
                        "pr_number": pr["number"],
                        "installation_id": installation_id,
                    },
                )
            ),
        )

    def _parse_pr_label(self, payload: dict, delivery_id: str | None) -> RawEvent | None:
        label = (payload.get("label") or {}).get("name", "")
        if label != _LABEL_REQUEST:
            return None

        pr = payload["pull_request"]
        if pr.get("draft"):
            return None

        repo = payload["repository"]
        installation_id = (payload.get("installation") or {}).get("id")
        normalized = {
            "trigger": "label_request",
            "subject": "pr",
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
            "installation_id": installation_id,
        }
        return RawEvent(
            event_id=delivery_id or str(uuid.uuid4()),
            source_channel="github",
            received_at=datetime.now(UTC),
            raw_payload=payload,
            normalized=normalized,
            response_routing=ResponseRouting(
                primary=ChannelTarget(
                    channel="github",
                    target={
                        "repo": repo["full_name"],
                        "pr_number": pr["number"],
                        "installation_id": installation_id,
                    },
                )
            ),
        )

    def _parse_comment_trigger(self, payload: dict, delivery_id: str | None) -> RawEvent | None:
        body = (payload.get("comment") or {}).get("body", "").strip()
        if not body.startswith("!리뷰"):
            return None

        issue = payload["issue"]
        # Only handle comments on PRs (issues have no pull_request field)
        if not issue.get("pull_request"):
            log.info("github.webhook.comment_trigger.not_a_pr", issue=issue["number"])
            return None

        repo = payload["repository"]
        installation_id = (payload.get("installation") or {}).get("id")
        normalized = {
            "trigger": "comment_request",
            "subject": "pr",
            "repo": {
                "owner": repo["owner"]["login"],
                "name": repo["name"],
                "full_name": repo["full_name"],
            },
            "pr": {
                "number": issue["number"],
                "title": issue["title"],
                "description": issue.get("body") or "",
                "author": issue["user"]["login"],
                "url": issue["html_url"],
            },
            "installation_id": installation_id,
        }
        return RawEvent(
            event_id=delivery_id or str(uuid.uuid4()),
            source_channel="github",
            received_at=datetime.now(UTC),
            raw_payload=payload,
            normalized=normalized,
            response_routing=ResponseRouting(
                primary=ChannelTarget(
                    channel="github",
                    target={
                        "repo": repo["full_name"],
                        "pr_number": issue["number"],
                        "installation_id": installation_id,
                    },
                )
            ),
        )

    def _parse_issue_label(self, payload: dict, delivery_id: str | None) -> RawEvent | None:
        label = (payload.get("label") or {}).get("name", "")
        if label != _LABEL_REQUEST:
            return None

        issue = payload["issue"]
        repo = payload["repository"]
        installation_id = (payload.get("installation") or {}).get("id")
        normalized = {
            "trigger": "label_request",
            "subject": "issue",
            "repo": {
                "owner": repo["owner"]["login"],
                "name": repo["name"],
                "full_name": repo["full_name"],
            },
            "issue": {
                "number": issue["number"],
                "title": issue["title"],
                "description": issue.get("body") or "",
                "author": issue["user"]["login"],
                "url": issue["html_url"],
            },
            "installation_id": installation_id,
        }
        return RawEvent(
            event_id=delivery_id or str(uuid.uuid4()),
            source_channel="github",
            received_at=datetime.now(UTC),
            raw_payload=payload,
            normalized=normalized,
            response_routing=ResponseRouting(
                primary=ChannelTarget(
                    channel="github",
                    target={
                        "repo": repo["full_name"],
                        "pr_number": issue["number"],
                        "installation_id": installation_id,
                    },
                )
            ),
        )
