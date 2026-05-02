"""Tests for agents.config.Settings.from_env.

ANTHROPIC_API_KEY is no longer required at config-load time — the
Claude Agent SDK handles auth (env var or Claude Code subscription
OAuth). The tests below confirm Settings.from_env succeeds without
it, that defaults populate, that overrides take effect, and that
empty optional vars are coerced to None.
"""

from __future__ import annotations


def test_from_env_succeeds_without_anthropic_api_key(monkeypatch):
    """Used to require ANTHROPIC_API_KEY; now any auth path is delegated
    to claude_agent_sdk so we no longer gate startup on it."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from agents.config import Settings

    s = Settings.from_env()  # would have raised under old behavior
    assert s.redis_url.startswith("redis://")


def test_from_env_defaults_when_minimum_provided(monkeypatch):
    # Clear optional vars to confirm defaults kick in.
    for v in (
        "REDIS_URL",
        "DATABASE_URL",
        "LOG_LEVEL",
        "AGENTS_CONSUMER_GROUP",
        "AGENTS_CONSUMER_NAME",
        "PROMPTS_DIR",
        "MODEL_CTO",
        "MODEL_DEFAULT",
        "REPORT_BASE_URL",
    ):
        monkeypatch.delenv(v, raising=False)

    from agents.config import Settings

    s = Settings.from_env()
    assert s.redis_url == "redis://localhost:6379"
    assert s.database_url is None
    assert s.log_level == "INFO"
    assert s.consumer_group == "agents"
    assert s.consumer_name == "agents-1"
    assert s.prompts_dir == "/app/prompts"
    assert s.model_cto == "claude-opus-4-7"
    assert s.model_default == "claude-sonnet-4-6"
    assert s.report_base_url is None


def test_from_env_overrides_take_effect(monkeypatch):
    """Each env var maps to the expected attribute (not silently dropped)."""
    monkeypatch.setenv("REDIS_URL", "redis://elsewhere:6380")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/x")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("MODEL_CTO", "claude-opus-4-7")
    monkeypatch.setenv("MODEL_DEFAULT", "claude-sonnet-4-6")
    monkeypatch.setenv("REPORT_BASE_URL", "https://example.test")

    from agents.config import Settings

    s = Settings.from_env()
    assert s.redis_url == "redis://elsewhere:6380"
    assert s.database_url == "postgresql://u:p@db/x"
    assert s.log_level == "DEBUG"
    assert s.report_base_url == "https://example.test"


def test_from_env_treats_empty_optional_vars_as_unset(monkeypatch):
    """Empty string from .env is the same as missing for optional vars."""
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REPORT_BASE_URL", "")

    from agents.config import Settings

    s = Settings.from_env()
    assert s.database_url is None
    assert s.report_base_url is None
