import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    redis_url: str
    log_level: str
    consumer_group: str
    consumer_name: str
    github_token: str | None
    slack_bot_token: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            consumer_group=os.environ.get("EGRESS_CONSUMER_GROUP", "egress"),
            consumer_name=os.environ.get("EGRESS_CONSUMER_NAME", "egress-1"),
            github_token=os.environ.get("GITHUB_TOKEN") or None,
            slack_bot_token=os.environ.get("SLACK_BOT_TOKEN") or None,
        )
