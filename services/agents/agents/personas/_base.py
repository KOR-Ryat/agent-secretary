"""Persona agent base.

Wraps a single-turn LLM call: loads system prompt from file, sends a
structured user message, parses the JSON response into a Pydantic model.

The actual LLM call goes through ``agents.llm.call_text`` which uses
``claude_agent_sdk.query`` under the hood — that lets the agents
service authenticate against either an ``ANTHROPIC_API_KEY`` or a
Claude Code subscription without code changes.

Each concrete persona (lead/specialist/dispatcher/cto) subclasses this
and specifies its prompt path, output type, and model.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from agents import llm
from agents.logging import get_logger

log = get_logger("agents.personas")

T = TypeVar("T", bound=BaseModel)


class PersonaCallError(RuntimeError):
    """Raised when a persona call fails after retries (e.g., output parse failure)."""


class PersonaAgent(Generic[T]):
    persona_id: str
    """Stable identifier used in trace/logs (e.g., 'security_lead', 'cto')."""

    prompt_path: str
    """Path relative to PROMPTS_DIR (e.g., 'leads/quality.md')."""

    output_model: type[T]
    """Pydantic model the response JSON is validated against."""

    model: str
    """Anthropic model id."""

    def __init__(self, prompts_dir: Path) -> None:
        self._system_prompt = (prompts_dir / self.prompt_path).read_text(encoding="utf-8")

    async def call(self, user_input: dict) -> T:
        """Invoke the persona with a structured input dict.

        The user_input is JSON-serialized and sent as the user message,
        wrapped with an instruction to respond in JSON matching the schema.
        """
        user_message = self._build_user_message(user_input)
        log.info("persona.call.start", persona=self.persona_id, model=self.model)
        text = await llm.call_text(
            system_prompt=self._system_prompt,
            user_message=user_message,
            model=self.model,
            persona_id=self.persona_id,
        )
        log.info("persona.call.complete", persona=self.persona_id)
        return self._parse(text)

    def _build_user_message(self, user_input: dict) -> str:
        schema_summary = json.dumps(
            self.output_model.model_json_schema(), ensure_ascii=False, indent=2
        )
        payload = json.dumps(user_input, ensure_ascii=False, indent=2)
        return (
            "다음 입력에 대해 시스템 프롬프트의 지침대로 평가하고, "
            "응답은 반드시 아래 JSON 스키마에 맞춰 JSON 만 출력합니다 "
            "(코드펜스 ```json ... ``` 안에 출력).\n\n"
            f"## 출력 스키마 (JSON Schema)\n```json\n{schema_summary}\n```\n\n"
            f"## 입력\n```json\n{payload}\n```\n"
        )

    def _parse(self, text: str) -> T:
        json_text = _extract_json_block(text)
        try:
            return self.output_model.model_validate_json(json_text)
        except ValidationError as e:
            log.error(
                "persona.output.invalid",
                persona=self.persona_id,
                error=str(e),
                raw=text[:500],
            )
            raise PersonaCallError(f"{self.persona_id} produced invalid JSON: {e}") from e


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json_block(text: str) -> str:
    """Extract a JSON object from the model's response text.

    Prefers fenced code blocks; falls back to the first {...} balanced span.
    """
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1)
    # Fallback: find first balanced JSON object
    start = text.find("{")
    if start == -1:
        return text.strip()
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:].strip()
