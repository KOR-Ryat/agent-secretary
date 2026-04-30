"""Channel parser ABC.

Each channel parser handles input verification and normalization for one channel.
"""

from abc import ABC, abstractmethod

from agent_secretary_schemas import RawEvent
from fastapi import APIRouter


class ChannelParser(ABC):
    name: str

    @abstractmethod
    def register_routes(self, router: APIRouter) -> None: ...

    @abstractmethod
    async def parse(self, *args, **kwargs) -> RawEvent | None:
        """Verify and parse a channel-specific request into a RawEvent.

        Return None if the request is valid but should not produce an event
        (e.g., GitHub `ping` events, draft PR events we want to ignore).
        """
