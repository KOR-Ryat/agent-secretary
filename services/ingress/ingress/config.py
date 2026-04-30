import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    redis_url: str
    github_webhook_secret: str | None
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379"),
            github_webhook_secret=os.environ.get("GITHUB_WEBHOOK_SECRET") or None,
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
