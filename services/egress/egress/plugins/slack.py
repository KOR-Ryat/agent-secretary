"""Slack channel deliverer.

Posts the workflow result back to the originating Slack thread:

  - Removes the `hourglass_flowing_sand` reaction (added by ingress on receipt).
  - Adds `white_check_mark` (success) or `x` (error) reaction on `mention_ts`.
  - Posts `summary_markdown` as a thread message, with a `📄 Full report`
    link appended when `result.trace_url` is set.

Detail content is *not* attached as a file — agents writes it to the
trace store and the report viewer (`/static/reports/{task_id}`) renders
it on demand. If `REPORT_BASE_URL` is unset, agents won't fill
`trace_url` and only the summary appears in Slack.

Reaction state on Slack is best-effort — if a reaction call fails (already
removed, message gone, permission), we log and continue.
"""

from __future__ import annotations

from agent_secretary_schemas import ResultEvent
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from egress.logging import get_logger
from egress.plugins._base import ChannelDeliverer

log = get_logger("egress.plugins.slack")

REACTION_PROGRESS = "hourglass_flowing_sand"
REACTION_SUCCESS = "white_check_mark"
REACTION_ERROR = "x"


class SlackDeliverer(ChannelDeliverer):
    name = "slack"

    def __init__(self, bot_token: str | None) -> None:
        self._token = bot_token
        self._web = AsyncWebClient(token=bot_token) if bot_token else None

    async def deliver(self, result: ResultEvent) -> None:
        target = result.response_routing.primary.target
        channel_id = target.get("channel_id")
        thread_ts = target.get("thread_ts")
        mention_ts = target.get("mention_ts")

        if not channel_id:
            log.warning("slack.deliver.missing_channel", result_id=result.result_id)
            return
        if self._web is None:
            log.warning(
                "slack.deliver.no_token",
                result_id=result.result_id,
                hint="set SLACK_BOT_TOKEN; skipping",
            )
            return

        is_error = bool(result.output.get("error"))

        # 1. Update reactions on the original mention.
        if mention_ts:
            await self._swap_reactions(channel_id, mention_ts, is_error)

        # 2. Post summary (+ optional report URL) in-thread.
        body = _compose_message(result)
        try:
            await self._web.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=body,
            )
            log.info(
                "slack.deliver.message_posted",
                result_id=result.result_id,
                channel=channel_id,
                with_report_url=bool(result.trace_url),
            )
        except SlackApiError as e:
            log.error(
                "slack.deliver.post_failed",
                result_id=result.result_id,
                error=str(e),
            )
            raise

    async def _swap_reactions(
        self, channel: str, mention_ts: str, is_error: bool
    ) -> None:
        await self._safe_reaction_remove(channel, mention_ts, REACTION_PROGRESS)
        await self._safe_reaction_add(
            channel, mention_ts, REACTION_ERROR if is_error else REACTION_SUCCESS
        )

    async def _safe_reaction_remove(self, channel: str, ts: str, name: str) -> None:
        assert self._web is not None
        try:
            await self._web.reactions_remove(channel=channel, timestamp=ts, name=name)
        except SlackApiError as e:
            # Common: "no_reaction" — hourglass was never added (e.g. ingress
            # crashed before reacting). Not actionable; log at debug level.
            log.debug("slack.reaction.remove_failed", name=name, error=str(e))

    async def _safe_reaction_add(self, channel: str, ts: str, name: str) -> None:
        assert self._web is not None
        try:
            await self._web.reactions_add(channel=channel, timestamp=ts, name=name)
        except SlackApiError as e:
            log.warning("slack.reaction.add_failed", name=name, error=str(e))

    async def close(self) -> None:
        if self._web is not None:
            # AsyncWebClient uses aiohttp; close its underlying session.
            await self._web.close()


def _compose_message(result: ResultEvent) -> str:
    body = result.summary_markdown
    if result.trace_url:
        body = f"{body}\n\n📄 <{result.trace_url}|Full report>"
    return body
