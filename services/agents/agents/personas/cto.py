"""CTO persona — meta-judge that synthesizes lead outputs into a 3-way decision."""

from __future__ import annotations

from agent_secretary_schemas.personas import CtoOutput

from agents.personas._base import PersonaAgent


class Cto(PersonaAgent[CtoOutput]):
    persona_id = "cto"
    prompt_path = "cto.md"
    output_model = CtoOutput

    def __init__(self, client, prompts_dir, model: str) -> None:
        self.model = model
        super().__init__(client, prompts_dir)
