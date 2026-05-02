"""Dispatcher persona — decides which leads/specialists to activate for a PR."""

from __future__ import annotations

from pathlib import Path

from agent_secretary_schemas.personas import DispatcherOutput

from agents.personas._base import PersonaAgent


class Dispatcher(PersonaAgent[DispatcherOutput]):
    persona_id = "dispatcher"
    prompt_path = "dispatcher.md"
    output_model = DispatcherOutput

    def __init__(self, prompts_dir: Path, model: str) -> None:
        self.model = model
        super().__init__(prompts_dir)
