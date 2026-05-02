"""Single-shot text-in / text-out wrapper around ``claude_agent_sdk.query``.

Personas + monolithic_review need a one-turn call with no tools. The
SDK's ``query()`` is an agent loop, so we constrain it with
``tools=[]`` (built-in tools disabled) and ``max_turns=1`` (no follow-up
turns) to make it behave like a plain ``messages.create``.

Why the SDK over the bare Anthropic Python SDK: the SDK transparently
authenticates against either an ``ANTHROPIC_API_KEY`` or a Claude Code
subscription OAuth token, so the same agents service can run against
either credential type without code changes. The bare Anthropic SDK
only accepts API keys.

Token usage from the ``ResultMessage`` is recorded into the active
``UsageAccumulator`` when a ``usage_scope()`` is open. Outside a scope
the call still works — recording is a no-op.
"""

from __future__ import annotations

import os
import shutil
import tempfile

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from agents import usage as usage_mod


async def call_text(
    *,
    system_prompt: str,
    user_message: str,
    model: str,
    persona_id: str,
) -> str:
    """Run a single-turn, tools-disabled query and return assistant text.

    ``persona_id`` is used as the usage record key — the dashboard's
    per-persona cost report would need it later if we ever break it
    out.
    """
    # Each call gets its own HOME so parallel CLI subprocesses don't
    # corrupt the shared ~/.claude.json (GrowthBook cache) via concurrent writes.
    tmp_home = tempfile.mkdtemp(prefix="claude-home-")
    real_home = os.environ.get("HOME", "/root")
    claude_src = os.path.join(real_home, ".claude")
    claude_dst = os.path.join(tmp_home, ".claude")
    if os.path.isdir(claude_src):
        shutil.copytree(claude_src, claude_dst, symlinks=True)

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model,
        tools=[],
        max_turns=1,
        permission_mode="bypassPermissions",
        env={"HOME": tmp_home},
    )
    chunks: list[str] = []
    result_msg: ResultMessage | None = None
    try:
        async for message in query(prompt=user_message, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
            elif isinstance(message, ResultMessage):
                result_msg = message
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)

    # ResultMessage.result is the SDK's flattened final answer; fall
    # back to concatenated assistant text if absent (mirrors the
    # pattern in code_analyze.py).
    text = ""
    if result_msg is not None and result_msg.result:
        text = result_msg.result
    if not text:
        text = "".join(chunks)

    if result_msg is not None:
        _record_usage(persona_id, model, result_msg)
    return text


def _record_usage(
    persona_id: str, configured_model: str, result: ResultMessage
) -> None:
    """Push token counts from a ResultMessage into the active accumulator.

    Prefers ``model_usage`` (per-model breakdown); falls back to the
    flat ``usage`` dict keyed under the configured model id.
    """
    acc = usage_mod.current()
    if acc is None:
        return
    if result.model_usage:
        for model, m in result.model_usage.items():
            acc.record(
                persona_id=persona_id,
                model=model,
                input_tokens=int(m.get("input_tokens", 0) or 0),
                output_tokens=int(m.get("output_tokens", 0) or 0),
                cache_read_tokens=int(m.get("cache_read_input_tokens", 0) or 0),
                cache_creation_tokens=int(m.get("cache_creation_input_tokens", 0) or 0),
            )
        return
    if result.usage:
        u = result.usage
        acc.record(
            persona_id=persona_id,
            model=configured_model,
            input_tokens=int(u.get("input_tokens", 0) or 0),
            output_tokens=int(u.get("output_tokens", 0) or 0),
            cache_read_tokens=int(u.get("cache_read_input_tokens", 0) or 0),
            cache_creation_tokens=int(u.get("cache_creation_input_tokens", 0) or 0),
        )
