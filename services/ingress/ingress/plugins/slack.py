"""Slack channel parser (Socket Mode).

Receives `app_mention` events and button-block clicks from Slack via
Socket Mode, normalizes them into a `RawEvent`, and publishes to the
ingress queue. Service/repo context is resolved from the channel ID
via `agent_secretary_config.resolve_channel`.

Two interaction shapes are supported:

  1. **Direct keyword mention** — e.g. `@bot 분석 좀 해줘`.
     `classify_slack_text` matches the text to a workflow id;
     a RawEvent is published immediately.

  2. **Empty / unmatched mention** — `@bot` alone.
     A button block (🔍 분석 / 🔧 수정 / 📋 이슈) is posted in the thread.
     A button click arrives as an `interactive` Socket Mode request and
     produces the same RawEvent shape as a keyword mention would.

Reactions, result messages, and file attachments are *not* posted from
here — that's the Slack egress plugin's job.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime

from agent_secretary_config import (
    WORKFLOW_CODE_ANALYZE,
    WORKFLOW_CODE_MODIFY,
    WORKFLOW_LINEAR_ISSUE,
    ChannelResolution,
    classify_slack_text,
    resolve_channel,
)
from agent_secretary_schemas import ChannelTarget, RawEvent, ResponseRouting
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient

from ingress.logging import get_logger
from ingress.plugins._base import ChannelParser
from ingress.publisher import EventPublisher

log = get_logger("ingress.plugins.slack")


# action_id (button) → workflow id
_BUTTON_ACTION_TO_WORKFLOW = {
    "cmd_debug": WORKFLOW_CODE_ANALYZE,
    "cmd_fix": WORKFLOW_CODE_MODIFY,
    "cmd_issue": WORKFLOW_LINEAR_ISSUE,
}

_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")


class SlackChannelParser(ChannelParser):
    name = "slack"

    def __init__(
        self,
        app_token: str,
        bot_token: str,
        publisher: EventPublisher,
    ) -> None:
        self._app_token = app_token
        self._publisher = publisher
        self._web = AsyncWebClient(token=bot_token)
        self._socket = SocketModeClient(app_token=app_token, web_client=self._web)
        self._socket.socket_mode_request_listeners.append(self._on_request)

    async def start(self) -> None:
        log.info("slack.start")
        await self._socket.connect()

    async def stop(self) -> None:
        log.info("slack.stop")
        await self._socket.disconnect()
        await self._socket.close()

    # --- Socket Mode dispatch ------------------------------------------

    async def _on_request(
        self,
        client: SocketModeClient,
        req: SocketModeRequest,
    ) -> None:
        # Always ack first so Slack doesn't retry.
        await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

        try:
            if req.type == "events_api":
                event = (req.payload or {}).get("event") or {}
                if event.get("type") == "app_mention":
                    await self._on_mention(event)
            elif req.type == "interactive":
                await self._on_interactive(req.payload or {})
        except Exception as e:
            log.error("slack.dispatch.error", error=str(e), req_type=req.type)

    # --- Handlers -------------------------------------------------------

    async def _on_mention(self, event: dict) -> None:
        channel_id = event["channel"]
        thread_ts = event.get("thread_ts") or event["ts"]
        mention_ts = event["ts"]
        user = event.get("user")
        raw_text = event.get("text", "")
        text = _MENTION_RE.sub("", raw_text).strip()

        log.info(
            "slack.mention",
            channel=channel_id,
            user=user,
            thread_ts=thread_ts,
            text=text[:120],
        )

        workflow = classify_slack_text(text)
        if workflow is None:
            await self._post_command_block(channel_id, thread_ts, mention_ts)
            return

        event_obj = self._build_event(
            workflow=workflow,
            trigger="slack_mention",
            channel_id=channel_id,
            thread_ts=thread_ts,
            mention_ts=mention_ts,
            user=user,
            text=text,
            thread_messages=await self._fetch_thread(channel_id, thread_ts),
        )
        await self._publisher.publish(event_obj)
        log.info("slack.mention.published", event_id=event_obj.event_id, workflow=workflow)

    async def _on_interactive(self, payload: dict) -> None:
        action = (payload.get("actions") or [{}])[0]
        action_id = action.get("action_id")
        workflow = _BUTTON_ACTION_TO_WORKFLOW.get(action_id)
        if workflow is None:
            log.warning("slack.interactive.unknown_action", action_id=action_id)
            return

        try:
            ctx = json.loads(action.get("block_id") or "{}")
        except json.JSONDecodeError:
            log.warning("slack.interactive.bad_block_id", block_id=action.get("block_id"))
            return

        channel_id = ctx.get("channel") or (payload.get("channel") or {}).get("id") or ""
        thread_ts = ctx.get("thread_ts")
        mention_ts = ctx.get("mention_ts")
        block_msg_ts = (payload.get("container") or {}).get("message_ts")
        user = (payload.get("user") or {}).get("id")

        # Remove the buttons message — it's served its purpose.
        if block_msg_ts:
            try:
                await self._web.chat_delete(channel=channel_id, ts=block_msg_ts)
            except Exception as e:
                log.warning("slack.interactive.delete_failed", error=str(e))

        log.info(
            "slack.interactive",
            channel=channel_id,
            action_id=action_id,
            workflow=workflow,
        )

        event_obj = self._build_event(
            workflow=workflow,
            trigger="slack_button",
            channel_id=channel_id,
            thread_ts=thread_ts,
            mention_ts=mention_ts,
            user=user,
            text="",
            thread_messages=await self._fetch_thread(channel_id, thread_ts),
        )
        await self._publisher.publish(event_obj)
        log.info("slack.interactive.published", event_id=event_obj.event_id, workflow=workflow)

    # --- Slack helpers --------------------------------------------------

    async def _fetch_thread(self, channel_id: str, thread_ts: str | None) -> list[dict]:
        if not thread_ts:
            return []
        try:
            resp = await self._web.conversations_replies(channel=channel_id, ts=thread_ts)
            messages = resp.get("messages") or []
            return [
                {
                    "user": m.get("user") or m.get("bot_id") or "?",
                    "text": (m.get("text") or "")[:1000],
                    "ts": m.get("ts"),
                }
                for m in messages
            ]
        except Exception as e:
            log.warning("slack.thread.fetch_failed", error=str(e))
            return []

    async def _post_command_block(
        self,
        channel_id: str,
        thread_ts: str,
        mention_ts: str,
    ) -> None:
        ctx_json = json.dumps(
            {"channel": channel_id, "thread_ts": thread_ts, "mention_ts": mention_ts}
        )
        blocks = [
            {
                "type": "actions",
                "block_id": ctx_json,
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🔍 버그 분석"},
                        "action_id": "cmd_debug",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🔧 버그 수정"},
                        "style": "primary",
                        "action_id": "cmd_fix",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📋 이슈 등록"},
                        "action_id": "cmd_issue",
                    },
                ],
            },
        ]
        try:
            await self._web.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                blocks=blocks,
                text="커맨드를 선택하세요.",
            )
        except Exception as e:
            log.warning("slack.button_block.post_failed", error=str(e))

    # --- RawEvent build -------------------------------------------------

    def _build_event(
        self,
        *,
        workflow: str,
        trigger: str,
        channel_id: str,
        thread_ts: str | None,
        mention_ts: str | None,
        user: str | None,
        text: str,
        thread_messages: list[dict],
    ) -> RawEvent:
        resolution: ChannelResolution = resolve_channel(channel_id)

        normalized = {
            "trigger": trigger,
            "workflow": workflow,
            "channel_id": channel_id,
            "channel_name": resolution.channel_name,
            "thread_ts": thread_ts,
            "mention_ts": mention_ts,
            "user": user,
            "text": text,
            "thread_messages": thread_messages,
            "service_resolution": {
                "service": resolution.service,
                "env": resolution.env,
                "repos": [r.model_dump() for r in resolution.repos],
            },
        }

        response_routing = ResponseRouting(
            primary=ChannelTarget(
                channel="slack",
                target={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "mention_ts": mention_ts,
                },
            ),
        )

        return RawEvent(
            event_id=str(uuid.uuid4()),
            source_channel="slack",
            received_at=datetime.now(UTC),
            raw_payload={"workflow": workflow, "channel_id": channel_id},
            normalized=normalized,
            response_routing=response_routing,
        )
