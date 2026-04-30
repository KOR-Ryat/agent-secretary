"""Code-analyze workflow.

Slack-driven, single-agent workflow ported from the legacy `debug` command.
A Claude Agent SDK `query()` runs against pre-mounted git worktrees and
returns a `{메시지, 파일}` JSON which we split into summary + detail.

Stages:
  1. Resolve repos for the channel (workflow_input.service_resolution).
  2. Mount each repo as a worktree on the env-appropriate branch.
  3. Run the agent with the system prompt + user context.
  4. Parse the agent's JSON output → summary_markdown / detail_markdown.

If the channel isn't bound to any service, the workflow short-circuits
to an error result (egress posts ❌ in Slack).
"""

from __future__ import annotations

import json
import re
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from agent_secretary_config import Repo
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from agents.config import Settings
from agents.logging import get_logger
from agents.skills.workspace import WorkspaceManager, WorkspaceSettings

log = get_logger("agents.workflows.code_analyze")


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class CodeAnalyzeRunner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        prompts_dir = Path(settings.prompts_dir)
        self._system_prompt = (prompts_dir / "workflows" / "code_analyze.md").read_text(
            encoding="utf-8"
        )
        self._workspace = WorkspaceManager(WorkspaceSettings.from_env())

    async def run(self, workflow_input: dict[str, Any]) -> dict[str, Any]:
        sr = workflow_input.get("service_resolution") or {}
        env = sr.get("env") or "production"
        repos_data = sr.get("repos") or []
        channel_name = workflow_input.get("channel_name") or "?"
        text = workflow_input.get("text") or ""
        thread_messages = workflow_input.get("thread_messages") or []

        if not repos_data:
            log.warning("workflow.code_analyze.no_service", channel=channel_name)
            return _error_result(
                summary=f"`{channel_name}` 채널은 등록된 서비스에 매핑되어 있지 않습니다. "
                f"`agent_secretary_config.service_map.SERVICE_MAP` 에 추가 필요.",
            )

        repos = [Repo(**r) for r in repos_data]
        session_id = uuid.uuid4().hex[:8]
        log.info(
            "workflow.code_analyze.start",
            channel=channel_name,
            env=env,
            repos=[r.short_name for r in repos],
            session_id=session_id,
        )

        async with AsyncExitStack() as stack:
            mounts: list[tuple[Repo, str, Path]] = []
            for repo in repos:
                branch = _branch_for_env(repo, env)
                wt = await stack.enter_async_context(
                    self._workspace.mount(repo, branch, session_id)
                )
                mounts.append((repo, branch, wt))

            prompt = _build_user_message(
                channel_name=channel_name,
                service=sr.get("service") or "?",
                env=env,
                mounts=mounts,
                thread_messages=thread_messages,
                user_text=text,
                session_id=session_id,
            )
            agent_text = await self._invoke_agent(prompt)

        parsed = _parse_output(agent_text)
        if parsed is None:
            log.warning(
                "workflow.code_analyze.unparseable_output",
                session_id=session_id,
                head=agent_text[:200],
            )
            return _error_result(
                summary="에이전트 응답에서 JSON 을 추출하지 못했습니다.",
                detail=agent_text,
            )

        log.info(
            "workflow.code_analyze.complete",
            session_id=session_id,
            message_len=len(parsed.get("메시지", "")),
            file_len=len(parsed.get("파일", "")),
        )

        return {
            "summary_markdown": parsed.get("메시지") or "(빈 응답)",
            "detail_markdown": parsed.get("파일") or None,
            "session_id": session_id,
            "service": sr.get("service"),
            "env": env,
            "mounted_repos": [
                {"name": r.name, "branch": b, "path": str(p)} for r, b, p in mounts
            ],
        }

    async def _invoke_agent(self, prompt: str) -> str:
        options = ClaudeAgentOptions(
            system_prompt=self._system_prompt,
            cwd=str(self._workspace.workspace_dir),
            permission_mode="bypassPermissions",
            model=self._settings.model_default,
        )
        chunks: list[str] = []
        result_text: str | None = None

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
            elif isinstance(message, ResultMessage):
                result_text = getattr(message, "result", None)

        # `ResultMessage.result` is the agent's final flat answer when the
        # SDK summarizes; fall back to concatenated assistant text otherwise.
        return result_text or "".join(chunks)


# --- Helpers --------------------------------------------------------------


def _branch_for_env(repo: Repo, env: str) -> str:
    if env == "production":
        return repo.production
    if env in ("staging", "stage"):
        return repo.staging
    return repo.dev


def _build_user_message(
    *,
    channel_name: str,
    service: str,
    env: str,
    mounts: list[tuple[Repo, str, Path]],
    thread_messages: list[dict[str, Any]],
    user_text: str,
    session_id: str,
) -> str:
    repo_lines = "\n".join(
        f"- {r.name} (branch: `{b}`, path: `{p}`)" for r, b, p in mounts
    )
    thread_lines = (
        "\n".join(
            f"[{m.get('user') or '?'}] {(m.get('text') or '').strip()[:1000]}"
            for m in thread_messages
        )
        or "(스레드 메시지 없음)"
    )

    return (
        f"# 채널 컨텍스트\n"
        f"- channel: `{channel_name}`\n"
        f"- service: `{service}`\n"
        f"- env: `{env}`\n"
        f"- session_id: `{session_id}`\n\n"
        f"# 마운트된 레포\n{repo_lines}\n\n"
        f"# 스레드 메시지 (시간순)\n{thread_lines}\n\n"
        f"# 사용자 요청 (멘션 텍스트)\n{user_text or '(빈 멘션 — 스레드 컨텍스트만 참조)'}\n"
    )


def _parse_output(text: str) -> dict[str, Any] | None:
    """Extract `{메시지, 파일}` JSON from agent output."""
    if not text:
        return None
    match = _FENCE_RE.search(text)
    candidate = match.group(1) if match else _balanced(text)
    if candidate is None:
        return None
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _balanced(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _error_result(*, summary: str, detail: str | None = None) -> dict[str, Any]:
    return {
        "error": summary,
        "summary_markdown": f"❌ {summary}",
        "detail_markdown": detail,
    }
