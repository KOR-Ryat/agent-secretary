"""Quality lead persona (Tier 1, no specialists)."""

from __future__ import annotations

from pathlib import Path

from agent_secretary_schemas import LeadOutput

from agents.personas._base import PersonaAgent


class QualityLead(PersonaAgent[LeadOutput]):
    persona_id = "quality_lead"
    prompt_path = "leads/quality.md"
    output_model = LeadOutput

    def __init__(self, prompts_dir: Path, model: str) -> None:
        self.model = model
        super().__init__(prompts_dir)
