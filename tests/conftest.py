"""Shared test fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Make all in-repo packages importable in tests, regardless of which service
# venv they target. uv editable installs are picked up via the venv's site-packages
# already; this is a belt-and-suspenders for local pytest runs.
for path in [
    REPO_ROOT / "packages" / "schemas",
    REPO_ROOT / "services" / "ingress",
    REPO_ROOT / "services" / "core",
    REPO_ROOT / "services" / "agents",
    REPO_ROOT / "services" / "egress",
]:
    sys.path.insert(0, str(path))
