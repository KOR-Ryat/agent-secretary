"""Channel parser ABC.

Each channel parser handles input verification and normalization for one
channel. Plugins fall into two shapes:

  - **HTTP-driven** (GitHub webhooks, CLI submit): override `register_routes`
    to mount FastAPI endpoints; `start`/`stop` stay no-op.
  - **Long-lived connection** (Slack Socket Mode): override `start`/`stop`
    to manage a background task; `register_routes` may stay no-op.
"""

from abc import ABC

from fastapi import APIRouter


class ChannelParser(ABC):
    name: str

    def register_routes(self, router: APIRouter) -> None:  # noqa: B027 — intentional default no-op
        """Mount HTTP endpoints. Default no-op for non-HTTP plugins."""

    async def start(self) -> None:  # noqa: B027 — intentional default no-op
        """Start any background work (e.g., Socket Mode listener)."""

    async def stop(self) -> None:  # noqa: B027 — intentional default no-op
        """Stop background work; called from FastAPI shutdown."""
