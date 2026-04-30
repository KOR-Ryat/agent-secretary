"""Channel-agnostic summary markdown generation for ResultEvent.

Egress plugins receive `summary_markdown` already and can use it directly,
trimming or wrapping per channel constraints.
"""

from __future__ import annotations

from typing import Any


def render_summary_markdown(workflow_output: dict[str, Any]) -> str:
    cto = workflow_output.get("cto_output", {})
    decision = cto.get("decision", "?")
    confidence = cto.get("confidence", 0.0)
    reasoning = cto.get("reasoning", "")
    triggers = cto.get("trigger_signals", []) or []
    risk = cto.get("risk_metadata", {}) or {}

    lines = [
        "## 🤖 agent-secretary review",
        "",
        f"**Decision:** `{decision}`  ·  **Confidence:** {confidence:.2f}",
        "",
    ]
    if triggers:
        lines.append("**Trigger signals:**")
        lines.extend(f"- {t}" for t in triggers)
        lines.append("")

    high_risk = risk.get("high_risk_paths_touched") or []
    if high_risk:
        lines.append(f"**High-risk paths:** {', '.join(high_risk)}")
        lines.append("")

    if reasoning:
        lines.append(f"_{reasoning}_")
        lines.append("")

    leads = workflow_output.get("lead_outputs") or []
    if leads:
        lines.append("**Lead findings:**")
        for lead in leads:
            findings = lead.get("findings") or []
            if not findings:
                lines.append(
                    f"- **{lead.get('persona', '?')}** — no findings "
                    f"(relevance {lead.get('domain_relevance', 0):.2f})"
                )
                continue
            for f in findings:
                lines.append(
                    f"- **{lead.get('persona', '?')}** "
                    f"_{f.get('severity', '?')}_ "
                    f"`{f.get('location', '')}` — {f.get('description', '')}"
                )
        lines.append("")

    lines.append("_Phase 1 shadow mode — no merge action taken._")
    return "\n".join(lines)
