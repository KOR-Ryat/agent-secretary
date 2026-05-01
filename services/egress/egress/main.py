"""Egress service consumer loop.

Reads ResultEvent from `results` stream, routes to the appropriate channel
deliverer based on `response_routing.primary.channel` (and any `additional`
targets). ack on success, dlq after MAX_DELIVERIES.
"""

from __future__ import annotations

import asyncio

from agent_secretary_config import GitHubAppAuth, MAX_DELIVERIES
from agent_secretary_schemas import ResultEvent
from redis.asyncio import Redis

from egress.config import Settings
from egress.logging import configure_logging, get_logger
from egress.plugins._base import ChannelDeliverer
from egress.plugins.cli import CliDeliverer
from egress.plugins.github import GithubDeliverer
from egress.plugins.slack import SlackDeliverer
from egress.queue import EgressQueue

log = get_logger("egress.main")


def _build_deliverers(settings: Settings) -> dict[str, ChannelDeliverer]:
    try:
        github_auth: GitHubAppAuth | None = GitHubAppAuth.from_env()
    except RuntimeError:
        github_auth = None
    return {
        "github": GithubDeliverer(github_auth),
        "slack": SlackDeliverer(settings.slack_bot_token),
        "cli": CliDeliverer(),
    }


async def _deliver_all(
    deliverers: dict[str, ChannelDeliverer], result: ResultEvent
) -> None:
    targets = [result.response_routing.primary, *result.response_routing.additional]
    for target in targets:
        deliverer = deliverers.get(target.channel)
        if deliverer is None:
            log.warning(
                "egress.deliverer.missing",
                channel=target.channel,
                result_id=result.result_id,
            )
            continue
        await deliverer.deliver(result)


async def run() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    log.info("egress.starting", redis_url=settings.redis_url)

    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    queue = EgressQueue(redis, settings.consumer_group, settings.consumer_name)
    await queue.ensure_group()
    deliverers = _build_deliverers(settings)
    log.info("egress.consumer_ready", channels=list(deliverers.keys()))

    try:
        async for message_id, result, delivery in queue.consume():
            log.info(
                "egress.result.received",
                message_id=message_id,
                result_id=result.result_id,
                channel=result.response_routing.primary.channel,
                delivery=delivery,
            )
            try:
                await _deliver_all(deliverers, result)
            except Exception as e:
                log.error(
                    "egress.deliver.error",
                    result_id=result.result_id,
                    error=str(e),
                    delivery=delivery,
                )
                if delivery >= MAX_DELIVERIES:
                    await queue.to_dlq(message_id, result.model_dump_json(), str(e))
                continue

            await queue.ack(message_id)
    finally:
        for d in deliverers.values():
            await d.close()
        await queue.close()


if __name__ == "__main__":
    asyncio.run(run())
