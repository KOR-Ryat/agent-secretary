"""Pydantic schemas for persona / lead / CTO outputs.

These mirror the prompts in `prompts/_shared.md` and `prompts/cto.md`.
"""

from typing import Literal

from pydantic import BaseModel, Field


class Finding(BaseModel):
    severity: Literal["P0", "P1", "P2", "P3", "P4"]
    location: str
    description: str
    threat_or_impact: str
    suggestion: str = ""


# Domains used for cross-A/B comparison; matches the value of
# `PersonaOutput.domain` so findings from both styles can be tallied
# the same way.
ReviewDomain = Literal[
    "security", "quality", "ops", "compatibility", "product_ux"
]


class FindingWithDomain(Finding):
    """Finding tagged with its domain.

    Used by the monolithic A/B workflow where one agent produces all
    findings — the domain has to live on the finding itself rather
    than on a separating persona.
    """

    domain: ReviewDomain


class PersonaOutput(BaseModel):
    """Output schema for both leads and specialists.

    Specialists do not include `unresolved_specialist_dissent` (see LeadOutput).
    """

    persona: str
    domain: Literal["security", "quality", "ops", "compatibility", "product_ux"]
    domain_relevance: float = Field(ge=0.0, le=1.0)
    self_confidence: float = Field(ge=0.0, le=1.0)
    findings: list[Finding] = Field(default_factory=list)
    summary: str


class UnresolvedSpecialistDissent(BaseModel):
    specialist: str
    their_finding: str
    lead_reasoning_for_overruling: str


class LeadOutput(PersonaOutput):
    unresolved_specialist_dissent: list[UnresolvedSpecialistDissent] = Field(
        default_factory=list
    )


class DispatcherActivatedLead(BaseModel):
    name: str
    tier: int
    reason: str | None = None
    trigger_type: Literal["hard", "soft"] | None = None
    trigger_evidence: str | None = None


class DispatcherActivatedSpecialist(BaseModel):
    name: str
    lead: str
    trigger_type: Literal["hard", "soft"]
    trigger_evidence: str
    reasoning: str


class DispatcherSkippedSpecialist(BaseModel):
    name: str
    near_trigger_evidence: str
    reason_not_activated: str


class DispatcherAmbiguousDecision(BaseModel):
    decision_point: str
    what_was_unclear: str
    default_taken: str


class DispatcherOutput(BaseModel):
    activated_leads: list[DispatcherActivatedLead]
    activated_specialists: list[DispatcherActivatedSpecialist] = Field(default_factory=list)
    skipped_specialists_with_reason: list[DispatcherSkippedSpecialist] = Field(
        default_factory=list
    )
    ambiguous_decisions: list[DispatcherAmbiguousDecision] = Field(default_factory=list)
    dispatcher_confidence: float = Field(ge=0.0, le=1.0)


class RiskMetadata(BaseModel):
    high_risk_paths_touched: list[str] = Field(default_factory=list)
    lines_changed: int = 0
    test_ratio: float = 0.0
    dependency_changes: bool = False


class CtoUnresolvedDisagreement(BaseModel):
    persona_a: str
    concern_a: str
    persona_b: str
    counter_b: str


class CtoOutput(BaseModel):
    decision: Literal["auto-merge", "request-changes", "escalate-to-human"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    trigger_signals: list[str] = Field(default_factory=list)
    unresolved_disagreements: list[CtoUnresolvedDisagreement] = Field(default_factory=list)
    risk_metadata: RiskMetadata


class MonolithicReviewOutput(BaseModel):
    """Output of the monolithic A/B comparator workflow.

    A single LLM call produces the decision *and* every finding (with
    domain attribution). Shape mirrors what an A-side CTO would emit,
    plus a flat `findings` list — A's findings live on individual
    persona outputs, so they're not directly comparable without this
    flattening.

    `risk_metadata` is computed deterministically by the workflow runner
    (same code path as A) so the A/B comparison isolates *only the LLM
    behavior*.
    """

    decision: Literal["auto-merge", "request-changes", "escalate-to-human"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    findings: list[FindingWithDomain] = Field(default_factory=list)
    risk_metadata: RiskMetadata
