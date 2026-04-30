"""Channel deliverer ABC.

Each deliverer formats and dispatches a ResultEvent to a specific channel.
"""

from abc import ABC, abstractmethod

from agent_secretary_schemas import ResultEvent


class ChannelDeliverer(ABC):
    name: str

    @abstractmethod
    async def deliver(self, result: ResultEvent) -> None: ...

    async def close(self) -> None:  # noqa: B027 — intentional default no-op
        """Optional cleanup hook; subclasses may override."""
