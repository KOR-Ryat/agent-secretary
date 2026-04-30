"""Tests for agents.config.Settings.from_env.

The agents service refuses to start without ANTHROPIC_API_KEY — same
fail-fast posture as AGENT_WORKSPACE_DIR. Other env vars have sensible
defaults so they don't fail the load.
"""

from __future__ import annotations

import pytest


def test_from_env_requires_anthropic_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from agents.config import Settings

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is required"):
        Settings.from_env()


def test_from_env_defaults_when_minimum_provided(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
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
    assert s.anthropic_api_key == "sk-ant-test"
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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REPORT_BASE_URL", "")

    from agents.config import Settings

    s = Settings.from_env()
    assert s.database_url is None
    assert s.report_base_url is None
