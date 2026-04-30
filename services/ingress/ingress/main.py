"""Ingress FastAPI application.

Loads channel plugins, registers their routes, and serves webhook endpoints.
Each channel plugin handles its own auth/verification and publishes RawEvents
to Redis Streams.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from redis.asyncio import Redis

from ingress.config import Settings
from ingress.logging import configure_logging, get_logger
from ingress.plugins.cli import CliChannelParser
from ingress.plugins.github import GithubChannelParser
from ingress.publisher import EventPublisher

log = get_logger("ingress.main")


def _build_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        redis = Redis.from_url(settings.redis_url, decode_responses=False)
        publisher = EventPublisher(redis)
        app.state.publisher = publisher

        router = APIRouter()
        plugins = [
            GithubChannelParser(settings.github_webhook_secret, publisher),
            CliChannelParser(publisher),
        ]
        for plugin in plugins:
            plugin.register_routes(router)
            log.info("ingress.plugin.registered", plugin=plugin.name)
        app.include_router(router)

        yield
        await publisher.close()

    app = FastAPI(title="agent-secretary ingress", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


configure_logging(Settings.from_env().log_level)
app = _build_app(Settings.from_env())
