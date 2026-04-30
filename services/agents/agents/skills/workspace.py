"""Bare repo + worktree workspace manager.

Code-touching workflows (`code_analyze`, `code_modify`, ...) need to read
real source files, not just diffs. A naive `git clone` per session causes
contention on shared branches; the legacy system used **bare repos +
git worktrees** for session isolation, and we keep that pattern.

Layout (under `AGENT_WORKSPACE_DIR`, default `~/agent-workspace`):

    repos/                          # bare repos — git objects only
        viv-monorepo.git/
        project-201-server.git/
        ...
    worktrees/                      # session mounts (auto-cleaned)
        viv-monorepo--main--<sid>/
        ...

Use `WorkspaceManager.mount(repo, branch, session_id)` as an async
context manager — the worktree is removed when the block exits, even
on error. Concurrent sessions on the same branch are safe because each
gets its own worktree directory keyed by `session_id`.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from agent_secretary_config import Repo

from agents.logging import get_logger

log = get_logger("agents.skills.workspace")


# --- Settings ------------------------------------------------------------


@dataclass(frozen=True)
class WorkspaceSettings:
    workspace_dir: Path
    github_token: str | None
    git_executable: str = "git"

    @classmethod
    def from_env(cls) -> WorkspaceSettings:
        return cls(
            workspace_dir=Path(
                os.environ.get(
                    "AGENT_WORKSPACE_DIR",
                    str(Path.home() / "agent-workspace"),
                )
            ).expanduser(),
            github_token=os.environ.get("GITHUB_TOKEN") or None,
        )


# --- Errors --------------------------------------------------------------


class WorkspaceError(RuntimeError):
    """Raised when a git operation fails."""


# --- Manager -------------------------------------------------------------


class WorkspaceManager:
    """Owns the on-disk `repos/` and `worktrees/` layout."""

    def __init__(self, settings: WorkspaceSettings) -> None:
        self._settings = settings

    @property
    def workspace_dir(self) -> Path:
        return self._settings.workspace_dir

    @property
    def repos_dir(self) -> Path:
        return self._settings.workspace_dir / "repos"

    @property
    def worktrees_dir(self) -> Path:
        return self._settings.workspace_dir / "worktrees"

    def bare_path(self, repo: Repo) -> Path:
        return self.repos_dir / f"{repo.short_name}.git"

    def worktree_path(self, repo: Repo, branch: str, session_id: str) -> Path:
        return self.worktrees_dir / f"{repo.short_name}--{_slug(branch)}--{session_id}"

    # --- Public ops -----------------------------------------------------

    async def ensure_bare_repo(self, repo: Repo) -> Path:
        """Clone `repo` as bare if absent. Returns the bare-repo path."""
        bare = self.bare_path(repo)
        if bare.exists():
            return bare

        bare.parent.mkdir(parents=True, exist_ok=True)
        url = self._clone_url(repo)
        log.info("workspace.clone.start", repo=repo.name, dest=str(bare))
        await self._git("clone", "--bare", url, str(bare))
        log.info("workspace.clone.done", repo=repo.name)
        return bare

    async def fetch(self, repo: Repo) -> None:
        """`git fetch --all --prune` on the bare repo."""
        bare = self.bare_path(repo)
        if not bare.exists():
            raise WorkspaceError(f"bare repo missing: {bare}")
        await self._git("-C", str(bare), "fetch", "--all", "--prune")

    @asynccontextmanager
    async def mount(
        self,
        repo: Repo,
        branch: str,
        session_id: str,
        *,
        fetch_first: bool = True,
    ) -> AsyncIterator[Path]:
        """Mount `branch` as a worktree under a session-scoped path.

        On context exit, the worktree is removed. Bare repo is preserved.
        """
        await self.ensure_bare_repo(repo)
        if fetch_first:
            await self.fetch(repo)

        bare = self.bare_path(repo)
        wt = self.worktree_path(repo, branch, session_id)
        wt.parent.mkdir(parents=True, exist_ok=True)

        if wt.exists():
            # leftover from a crashed session — nuke before re-mounting.
            log.warning("workspace.worktree.stale_remove", path=str(wt))
            await self._git_silent("-C", str(bare), "worktree", "remove", "--force", str(wt))

        log.info(
            "workspace.worktree.add",
            repo=repo.name,
            branch=branch,
            session_id=session_id,
            path=str(wt),
        )
        # `--detach` lets multiple sessions mount the same branch concurrently:
        # each gets the branch's commit on a detached HEAD, so no worktree
        # claims ownership of the branch ref. Modify workflows create a new
        # session-scoped branch from there.
        await self._git("-C", str(bare), "worktree", "add", "--detach", str(wt), branch)

        try:
            yield wt
        finally:
            log.info("workspace.worktree.remove", path=str(wt))
            await self._git_silent("-C", str(bare), "worktree", "remove", "--force", str(wt))

    async def list_worktrees(self, repo: Repo) -> list[str]:
        """Return current worktree paths for a repo (debugging / cleanup tools)."""
        bare = self.bare_path(repo)
        if not bare.exists():
            return []
        out = await self._git_capture("-C", str(bare), "worktree", "list", "--porcelain")
        return [
            line.removeprefix("worktree ")
            for line in out.splitlines()
            if line.startswith("worktree ")
        ]

    # --- Internals ------------------------------------------------------

    def _clone_url(self, repo: Repo) -> str:
        token = self._settings.github_token
        if token:
            return f"https://{token}@github.com/{repo.name}.git"
        return f"https://github.com/{repo.name}.git"

    async def _git(self, *args: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            self._settings.git_executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise WorkspaceError(
                f"git {' '.join(args)} failed (rc={proc.returncode}):\n"
                f"{stderr.decode(errors='replace').strip()}"
            )

    async def _git_silent(self, *args: str) -> None:
        """Run a git command, ignoring failures (used for cleanup paths)."""
        proc = await asyncio.create_subprocess_exec(
            self._settings.git_executable,
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()

    async def _git_capture(self, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            self._settings.git_executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise WorkspaceError(
                f"git {' '.join(args)} failed (rc={proc.returncode}):\n"
                f"{stderr.decode(errors='replace').strip()}"
            )
        return stdout.decode()


def _slug(branch: str) -> str:
    """Sanitize a branch name for safe use in a directory name.

    Branches like `release/main/cbt` become `release_main_cbt`.
    """
    return branch.replace("/", "_").replace(" ", "_")
