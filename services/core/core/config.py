import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    redis_url: str
    log_level: str
    consumer_group: str
    consumer_name: str
    pr_review_ab_mode: bool
    """When True, a PR event produces TWO TaskSpecs: the primary
    `pr_review` task plus a shadow `pr_review_monolithic` task for
    issue #2's persona A/B comparison."""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            consumer_group=os.environ.get("CORE_CONSUMER_GROUP", "core"),
            consumer_name=os.environ.get("CORE_CONSUMER_NAME", "core-1"),
            pr_review_ab_mode=_bool_env("PR_REVIEW_AB_MODE", default=False),
        )
