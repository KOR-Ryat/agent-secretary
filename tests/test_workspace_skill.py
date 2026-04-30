"""Workspace skill integration test.

Exercises the bare-repo + worktree pattern using a real `git` binary
against a local fixture repo (no network). Skipped if `git` is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from agent_secretary_config import Repo
from agents.skills.workspace import (
    WorkspaceManager,
    WorkspaceSettings,
    _slug,
)


def _git_available() -> bool:
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(not _git_available(), reason="git not installed")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def fixture_origin(tmp_path: Path) -> Path:
    """Build a tiny non-bare 'origin' repo with two branches."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-b", "main")
    _git(origin, "config", "user.email", "t@t.t")
    _git(origin, "config", "user.name", "t")
    (origin / "a.txt").write_text("hello on main\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "init on main")

    _git(origin, "checkout", "-b", "feature/x")
    (origin / "a.txt").write_text("hello on feature/x\n")
    _git(origin, "commit", "-am", "feature change")
    _git(origin, "checkout", "main")
    return origin


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspaceManager:
    settings = WorkspaceSettings(
        workspace_dir=tmp_path / "ws",
        github_token=None,
    )
    return WorkspaceManager(settings)


@pytest.fixture
def fake_repo(fixture_origin: Path) -> Repo:
    # Use a Repo whose `clone URL` we override via monkeypatching below.
    return Repo(name="fixture/origin", production="main", staging="main", dev="main")


def test_slug_replaces_slashes_and_spaces():
    assert _slug("release/main/cbt") == "release_main_cbt"
    assert _slug("feature/x y") == "feature_x_y"
    assert _slug("main") == "main"


def test_from_env_requires_explicit_workspace_dir(monkeypatch):
    """No silent fallback to ~/agent-workspace. Misconfiguration must fail loud."""
    monkeypatch.delenv("AGENT_WORKSPACE_DIR", raising=False)
    with pytest.raises(RuntimeError, match="AGENT_WORKSPACE_DIR is required"):
        WorkspaceSettings.from_env()


def test_from_env_uses_explicit_value(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    s = WorkspaceSettings.from_env()
    assert s.workspace_dir == tmp_path / "ws"
    assert s.github_token is None


@pytest.mark.asyncio
async def test_mount_and_cleanup_around_real_branches(
    workspace: WorkspaceManager,
    fake_repo: Repo,
    fixture_origin: Path,
    monkeypatch,
):
    # Override clone URL to point at the local fixture; no network needed.
    monkeypatch.setattr(
        WorkspaceManager,
        "_clone_url",
        lambda self, repo: str(fixture_origin),
    )

    bare = await workspace.ensure_bare_repo(fake_repo)
    assert bare.exists() and bare.is_dir()
    assert bare.name == "origin.git"

    # Idempotent: second call doesn't re-clone.
    again = await workspace.ensure_bare_repo(fake_repo)
    assert again == bare

    async with workspace.mount(fake_repo, "main", session_id="abc123") as wt:
        assert wt.exists()
        assert (wt / "a.txt").read_text() == "hello on main\n"

    # Worktree dir gone after exit.
    assert not wt.exists()

    # Concurrent sessions on the same branch get distinct worktrees.
    async with workspace.mount(fake_repo, "feature/x", session_id="s1") as wt1:
        async with workspace.mount(fake_repo, "feature/x", session_id="s2") as wt2:
            assert wt1 != wt2
            assert wt1.exists()
            assert wt2.exists()
            assert (wt1 / "a.txt").read_text() == "hello on feature/x\n"
            assert (wt2 / "a.txt").read_text() == "hello on feature/x\n"


@pytest.mark.asyncio
async def test_mount_cleanup_runs_even_on_exception(
    workspace: WorkspaceManager,
    fake_repo: Repo,
    fixture_origin: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        WorkspaceManager,
        "_clone_url",
        lambda self, repo: str(fixture_origin),
    )

    captured_path: Path | None = None
    with pytest.raises(RuntimeError, match="boom"):
        async with workspace.mount(fake_repo, "main", session_id="ex") as wt:
            captured_path = wt
            raise RuntimeError("boom")

    assert captured_path is not None
    assert not captured_path.exists()
