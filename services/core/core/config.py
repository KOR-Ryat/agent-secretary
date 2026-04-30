import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    redis_url: str
    log_level: str
    consumer_group: str
    consumer_name: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            consumer_group=os.environ.get("CORE_CONSUMER_GROUP", "core"),
            consumer_name=os.environ.get("CORE_CONSUMER_NAME", "core-1"),
        )
