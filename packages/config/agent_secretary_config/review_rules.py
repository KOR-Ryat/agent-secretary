"""Heuristic patterns for PR review risk metadata.

These are intentionally simple defaults applied to *any* target codebase.
Per-codebase tuning is an open task (see design.md §12) — eventually these
will move behind a per-target config file or env-driven override layer.

For now they are module-level tuples so the agents service can import
them directly with no construction overhead.
"""

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
