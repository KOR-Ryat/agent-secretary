"""Compatibility lead persona (Tier 2, conditional)."""

from __future__ import annotations

from agent_secretary_schemas import LeadOutput

from agents.personas._base import PersonaAgent


class CompatibilityLead(PersonaAgent[LeadOutput]):
    persona_id = "compatibility_lead"
    prompt_path = "leads/compatibility.md"
    output_model = LeadOutput

    def __init__(self, client, prompts_dir, model: str) -> None:
        self.model = model
        super().__init__(client, prompts_dir)
