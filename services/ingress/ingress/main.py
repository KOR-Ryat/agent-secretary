"""Ingress FastAPI application.

Loads channel plugins, registers their routes, manages background
listeners, and serves webhook endpoints. Each channel plugin handles its
own auth/verification and publishes RawEvents to Redis Streams.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from redis.asyncio import Redis

from ingress.config import Settings
from ingress.logging import configure_logging, get_logger
from ingress.plugins._base import ChannelParser
from ingress.plugins.cli import CliChannelParser
from ingress.plugins.github import GithubChannelParser
from ingress.plugins.slack import SlackChannelParser
from ingress.publisher import EventPublisher

log = get_logger("ingress.main")


def _build_plugins(settings: Settings, publisher: EventPublisher) -> list[ChannelParser]:
    plugins: list[ChannelParser] = [
        GithubChannelParser(settings.github_webhook_secret, publisher),
        CliChannelParser(publisher),
    ]
    if settings.slack_app_token and settings.slack_bot_token:
        plugins.append(
            SlackChannelParser(
                app_token=settings.slack_app_token,
                bot_token=settings.slack_bot_token,
                publisher=publisher,
            )
        )
    else:
        log.info("ingress.slack.skipped", reason="SLACK_APP_TOKEN or SLACK_BOT_TOKEN missing")
    return plugins


def _build_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        redis = Redis.from_url(settings.redis_url, decode_responses=False)
        publisher = EventPublisher(redis)
        app.state.publisher = publisher

        router = APIRouter()
        plugins = _build_plugins(settings, publisher)
        for plugin in plugins:
            plugin.register_routes(router)
            log.info("ingress.plugin.registered", plugin=plugin.name)
        app.include_router(router)

        for plugin in plugins:
            await plugin.start()

        try:
            yield
        finally:
            for plugin in plugins:
                try:
                    await plugin.stop()
                except Exception as e:
                    log.warning("ingress.plugin.stop_failed", plugin=plugin.name, error=str(e))
            await publisher.close()

    app = FastAPI(title="agent-secretary ingress", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


configure_logging(Settings.from_env().log_level)
app = _build_app(Settings.from_env())
