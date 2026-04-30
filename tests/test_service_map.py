"""Smoke tests for service_map config."""

from __future__ import annotations

from agent_secretary_config import (
    SERVICE_MAP,
    Channel,
    Repo,
    all_repos,
    resolve_channel,
)


def test_service_map_has_four_services():
    assert set(SERVICE_MAP.keys()) == {"if", "ifcc", "viv", "zendi"}


def test_all_repos_are_unique_and_present():
    repos = all_repos()
    names = [r.name for r in repos]
    assert len(names) == len(set(names)), "duplicate repo entry"
    assert "mesher-labs/viv-monorepo" in names
    assert "mesher-labs/hokki-server" in names


def test_resolve_known_service_channel():
    res = resolve_channel("C099XH6QR97")  # if-payment-production
    assert res.service == "if"
    assert res.env == "production"
    assert res.channel_name == "if-payment-production"
    assert any(r.name == "mesher-labs/project-201-server" for r in res.repos)


def test_resolve_known_channel_outside_service_map():
    # general---공지 — present in CHANNEL_NAMES but not bound to a service
    res = resolve_channel("C057QR9PUBD")
    assert res.service is None
    assert res.env is None
    assert res.channel_name == "general---공지"
    assert res.repos == ()


def test_resolve_unknown_channel_falls_back_to_id():
    res = resolve_channel("CDOESNOTEXIST")
    assert res.service is None
    assert res.channel_name == "CDOESNOTEXIST"


def test_repo_short_name():
    repo = Repo(name="mesher-labs/hokki-server", production="master", staging="stage", dev="dev")
    assert repo.short_name == "hokki-server"


def test_models_are_frozen():
    repo = Repo(name="x/y", production="a", staging="b", dev="c")
    try:
        repo.production = "z"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Repo should be frozen")


def test_channel_env_strings_preserved_verbatim():
    """Legacy data uses both 'staging' and 'stage' — preserved as-is."""
    if_service = SERVICE_MAP["if"]
    ifcc_service = SERVICE_MAP["ifcc"]

    if_envs = {c.env for c in if_service.channels}
    ifcc_envs = {c.env for c in ifcc_service.channels}

    assert "staging" in if_envs   # if uses "staging"
    assert "stage" in ifcc_envs   # ifcc uses "stage"


def test_channel_model_construct():
    """Direct construction works (smoke for type usage)."""
    Channel(id="C0X", name="x", env="production")
