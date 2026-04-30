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


# --- Per-repo review-rule sanity checks ----------------------------------
#
# One assertion per repo on a distinctive value. These guard against a
# field being silently dropped or mis-edited later. They do NOT exhaust
# every prefix — that would lock the data into the test file.


def test_viv_monorepo_review_rules_match_monorepo_layout():
    rules = review_rules_for("mesher-labs/viv-monorepo")
    resolved = resolve_rules(rules)
    assert "server/src/modules/auth/" in resolved.high_risk_paths
    assert "server/src/modules/payment/" in resolved.high_risk_paths
    assert "server/src/database/migrations/" in resolved.high_risk_paths
    assert ".spec.ts" in resolved.test_file_patterns
    assert "_test.dart" in resolved.test_file_patterns
    assert "bun.lock" in resolved.dependency_file_patterns
    assert "pubspec.lock" in resolved.dependency_file_patterns


def test_project_201_server_review_rules_match_python_fastapi_layout():
    rules = review_rules_for("mesher-labs/project-201-server")
    resolved = resolve_rules(rules)
    assert "app/router/payment.py" in resolved.high_risk_paths
    assert "app/infrastructure/service/payment/" in resolved.high_risk_paths
    assert "supabase/migrations/" in resolved.high_risk_paths
    assert "test_" in resolved.test_file_patterns
    assert "pyproject.toml" in resolved.dependency_file_patterns
    assert "poetry.lock" in resolved.dependency_file_patterns


def test_project_201_flutter_review_rules_cover_iap_and_native_signing():
    rules = review_rules_for("mesher-labs/project-201-flutter")
    resolved = resolve_rules(rules)
    assert "lib/features/auth/" in resolved.high_risk_paths
    assert "lib/core/infrastructure/iap/" in resolved.high_risk_paths
    assert "android/app/google-services.json" in resolved.high_risk_paths
    assert "ios/Runner.xcodeproj/" in resolved.high_risk_paths
    assert "_test.dart" in resolved.test_file_patterns
    assert "pubspec.lock" in resolved.dependency_file_patterns


def test_if_character_chat_server_review_rules_match_python_layout():
    """Despite the unusual `release/main/cbt` branch name, auth/payment
    live at standard src/ paths — verify we didn't get fooled into using
    a cbt/ prefix."""
    rules = review_rules_for("mesher-labs/if-character-chat-server")
    resolved = resolve_rules(rules)
    assert "src/api/v1/auth.py" in resolved.high_risk_paths
    assert "src/api/v1/webhooks.py" in resolved.high_risk_paths
    assert "src/infrastructure/portone/" in resolved.high_risk_paths
    assert "src/infrastructure/polar/" in resolved.high_risk_paths
    assert "migrations/" in resolved.high_risk_paths
    assert not any("cbt/" in p for p in resolved.high_risk_paths)
    assert "test_" in resolved.test_file_patterns
    assert "pyproject.toml" in resolved.dependency_file_patterns


def test_if_character_chat_client_review_rules_falls_back_for_tests():
    """The client has no test framework configured — test_file_patterns
    is intentionally omitted so the module default applies."""
    rules = review_rules_for("mesher-labs/if-character-chat-client")
    resolved = resolve_rules(rules)
    assert "src/lib/payment/" in resolved.high_risk_paths
    assert "src/app/api/auth/" in resolved.high_risk_paths
    assert "src/services/paymentService.ts" in resolved.high_risk_paths
    # Test patterns omitted → fallback to module defaults.
    assert resolved.test_file_patterns == TEST_FILE_MARKERS
    assert "yarn.lock" in resolved.dependency_file_patterns


def test_hokki_server_review_rules_match_nestjs_mongodb_layout():
    rules = review_rules_for("mesher-labs/hokki-server")
    resolved = resolve_rules(rules)
    assert "src/auth/" in resolved.high_risk_paths
    assert "src/payment/" in resolved.high_risk_paths
    assert "src/in-app-payment/" in resolved.high_risk_paths
    # MongoDB repo: custom migration runner under src/scripts/migration/.
    assert "src/scripts/migration/" in resolved.high_risk_paths
    assert ".spec.ts" in resolved.test_file_patterns
    assert ".e2e-spec.ts" in resolved.test_file_patterns
    assert "yarn.lock" in resolved.dependency_file_patterns


def test_hokki_flutter_app_review_rules_cover_iap_and_native_signing():
    rules = review_rules_for("mesher-labs/hokki_flutter_app")
    resolved = resolve_rules(rules)
    assert "lib/core/auth/" in resolved.high_risk_paths
    # IAP is a single file rather than a dir in this repo.
    assert "lib/services/in_app_purchase_service.dart" in resolved.high_risk_paths
    assert "android/app/google-services.json" in resolved.high_risk_paths
    assert "_test.dart" in resolved.test_file_patterns
    assert "pubspec.lock" in resolved.dependency_file_patterns
