"""Per-repo ReviewRules tests."""

from __future__ import annotations

import dataclasses

import pytest
from agent_secretary_config import (
    DEPENDENCY_FILE_MARKERS,
    HIGH_RISK_PATH_TAGS,
    TEST_FILE_MARKERS,
    Repo,
    ReviewRules,
    resolve_rules,
    review_rules_for,
)


def test_review_rules_default_falls_back_to_module_defaults():
    resolved = resolve_rules(ReviewRules())
    assert resolved.high_risk_paths == HIGH_RISK_PATH_TAGS
    assert resolved.test_file_patterns == TEST_FILE_MARKERS
    assert resolved.dependency_file_patterns == DEPENDENCY_FILE_MARKERS


def test_review_rules_none_falls_back_to_defaults():
    resolved = resolve_rules(None)
    assert resolved.high_risk_paths == HIGH_RISK_PATH_TAGS


def test_review_rules_override_replaces_field():
    rules = ReviewRules(high_risk_paths=("server/src/auth/", "server/src/payment/"))
    resolved = resolve_rules(rules)
    assert resolved.high_risk_paths == (
        "server/src/auth/",
        "server/src/payment/",
    )
    # Other fields fall back to defaults.
    assert resolved.test_file_patterns == TEST_FILE_MARKERS
    assert resolved.dependency_file_patterns == DEPENDENCY_FILE_MARKERS


def test_review_rules_for_unknown_repo_returns_empty_rules():
    rules = review_rules_for("nobody/nothing")
    assert rules == ReviewRules()


def test_review_rules_for_known_repo_returns_repo_overrides():
    rules = review_rules_for("mesher-labs/viv-monorepo")
    # Currently no overrides set in service_map; returns empty defaults.
    assert isinstance(rules, ReviewRules)


def test_repo_can_carry_review_rules():
    repo = Repo(
        name="x/y",
        production="main",
        staging="stage",
        dev="dev",
        review_rules=ReviewRules(
            high_risk_paths=("lib/payment/",),
            test_file_patterns=("_test.go",),
        ),
    )
    resolved = resolve_rules(repo.review_rules)
    assert resolved.high_risk_paths == ("lib/payment/",)
    assert resolved.test_file_patterns == ("_test.go",)


def test_resolved_review_rules_is_frozen():
    resolved = resolve_rules(ReviewRules())
    with pytest.raises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
        resolved.high_risk_paths = ()  # type: ignore[misc]


def test_compute_risk_metadata_uses_repo_specific_paths(monkeypatch):
    """Verify the workflow consults per-repo rules via review_rules_for."""
    from agent_secretary_config import SERVICE_MAP, Channel, Repo, Service
    from agents.workflows.pr_review import _compute_risk_metadata

    # Inject a fake service+repo with custom high_risk_paths.
    fake_repo = Repo(
        name="fake-org/fake-repo",
        production="main",
        staging="stage",
        dev="dev",
        review_rules=ReviewRules(
            high_risk_paths=("custom-sensitive/",),
            test_file_patterns=("_test.go",),
        ),
    )
    fake_service = Service(key="fakesvc", repos=(fake_repo,), channels=())
    monkeypatch.setitem(SERVICE_MAP, "fakesvc", fake_service)
    # The lookup index is built once at import — patch it too.
    from agent_secretary_config import service_map as sm
    monkeypatch.setitem(
        sm._CHANNEL_INDEX,
        "fakeChannel",
        (fake_service, Channel(id="fakeChannel", name="x", env="production")),
    )

    pr = {
        "changed_files": [
            "custom-sensitive/handler.go",
            "internal/foo_test.go",
            "package.json",
        ],
        "diff_stats": {"additions": 30, "deletions": 5},
    }
    risk = _compute_risk_metadata(pr, "fake-org/fake-repo")
    assert "custom-sensitive/" in risk.high_risk_paths_touched
    # The default "auth/", "payments/" don't apply for this repo since the
    # override replaces them.
    assert "auth/" not in risk.high_risk_paths_touched
    # Test file detection uses repo-specific marker.
    assert risk.test_ratio > 0
    assert risk.dependency_changes is True


def test_compute_risk_metadata_unknown_repo_falls_back_to_defaults():
    """When repo isn't in SERVICE_MAP, defaults apply."""
    from agents.workflows.pr_review import _compute_risk_metadata

    pr = {
        "changed_files": ["auth/session.py"],
        "diff_stats": {"additions": 10, "deletions": 0},
    }
    risk = _compute_risk_metadata(pr, "nobody/nothing")
    assert "auth/" in risk.high_risk_paths_touched  # default applies
