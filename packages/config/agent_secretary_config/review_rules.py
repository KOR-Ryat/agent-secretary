"""Heuristic patterns for PR review risk metadata.

Two layers:

  1. Module-level *defaults* that apply to any target codebase. Conservative,
     generic patterns covering common conventions.
  2. Per-repo `ReviewRules` attached to each `Repo` in `service_map`.
     A repo may override any subset of the defaults; unset fields fall back.

The agents service resolves both layers at compute-time via
`review_rules_for(repo_full_name).resolved()` — see usage in
`services/agents/agents/workflows/pr_review.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

# --- Generic defaults ----------------------------------------------------

# Path prefixes/segments that mark high-risk PR areas. Touching any of
# these forces the CTO to escalate (see prompts/cto.md hard-rule table).
HIGH_RISK_PATH_TAGS: tuple[str, ...] = (
    "auth/",
    "payments/",
    "migrations/",
    "billing/",
    "secrets/",
)

# Substrings (case-insensitive) that mark a file as a test. Used to
# compute test_ratio in risk_metadata.
TEST_FILE_MARKERS: tuple[str, ...] = ("test", "spec")

# Substrings that mark a file as a dependency manifest/lockfile. Used to
# flag dependency_changes in risk_metadata.
DEPENDENCY_FILE_MARKERS: tuple[str, ...] = (
    "package.json",
    "lock",
    "requirements",
    "go.sum",
    "Cargo",
)


# --- Per-repo overrides --------------------------------------------------


class ReviewRules(BaseModel, frozen=True):
    """Per-repo review heuristics. Empty fields fall back to module defaults.

    Attach to a `Repo` in `SERVICE_MAP` to tune the review pipeline for a
    given codebase — e.g. viv-monorepo's auth lives under
    `server/src/modules/auth/`, not `auth/`.
    """

    # If non-empty, REPLACES the corresponding default for this repo.
    high_risk_paths: tuple[str, ...] = ()
    test_file_patterns: tuple[str, ...] = ()
    dependency_file_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedReviewRules:
    """Effective rule set after merging per-repo overrides with defaults."""

    high_risk_paths: tuple[str, ...]
    test_file_patterns: tuple[str, ...]
    dependency_file_patterns: tuple[str, ...]


def resolve_rules(rules: ReviewRules | None) -> ResolvedReviewRules:
    """Merge per-repo `rules` with module defaults.

    For each field: if the override is non-empty, use it; otherwise fall
    back to the default. `None` is treated the same as an empty
    `ReviewRules()`.
    """
    rules = rules or ReviewRules()
    return ResolvedReviewRules(
        high_risk_paths=rules.high_risk_paths or HIGH_RISK_PATH_TAGS,
        test_file_patterns=rules.test_file_patterns or TEST_FILE_MARKERS,
        dependency_file_patterns=(
            rules.dependency_file_patterns or DEPENDENCY_FILE_MARKERS
        ),
    )
