import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    redis_url: str
    database_url: str | None
    log_level: str
    consumer_group: str
    consumer_name: str
    prompts_dir: str
    model_cto: str
    model_default: str
    report_base_url: str | None
    """Public base URL of the report viewer, e.g. ``https://agent-secretary.foo.com``.
    When set, agents fill ``ResultEvent.trace_url`` so egress channels can
    link to ``{base}/static/reports/{task_id}``."""

    @classmethod
    def from_env(cls) -> "Settings":
        # No ANTHROPIC_API_KEY check: claude_agent_sdk authenticates against
        # either ANTHROPIC_API_KEY (env) or a Claude Code subscription OAuth
        # token. We let the SDK fail at first call rather than gating startup
        # on the env var — that way a MAX-subscription deployment doesn't
        # need a placeholder key.
        return cls(
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379"),
            database_url=os.environ.get("DATABASE_URL") or None,
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            consumer_group=os.environ.get("AGENTS_CONSUMER_GROUP", "agents"),
            consumer_name=os.environ.get("AGENTS_CONSUMER_NAME", "agents-1"),
            prompts_dir=os.environ.get("PROMPTS_DIR", "/app/prompts"),
            model_cto=os.environ.get("MODEL_CTO", "claude-opus-4-7"),
            model_default=os.environ.get("MODEL_DEFAULT", "claude-sonnet-4-6"),
            report_base_url=(os.environ.get("REPORT_BASE_URL") or None),
        )
