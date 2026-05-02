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

    return "\n".join(lines)


def render_detail_markdown(workflow_output: dict[str, Any]) -> str:
    """Full per-finding report for the static report viewer."""
    cto = workflow_output.get("cto_output", {})
    decision = cto.get("decision", "?")
    confidence = cto.get("confidence", 0.0)
    reasoning = cto.get("reasoning", "")
    triggers = cto.get("trigger_signals", []) or []
    disagreements = cto.get("unresolved_disagreements", []) or []
    risk = cto.get("risk_metadata", {}) or {}

    lines = [
        "# PR Review Report",
        "",
        f"**Decision:** `{decision}`  ·  **Confidence:** {confidence:.2f}",
        "",
    ]

    if reasoning:
        lines += [f"> {reasoning}", ""]

    if triggers:
        lines += ["## Trigger Signals", ""]
        lines += [f"- {t}" for t in triggers]
        lines.append("")

    high_risk = risk.get("high_risk_paths_touched") or []
    lines_changed = risk.get("lines_changed", 0)
    test_ratio = risk.get("test_ratio", 0.0)
    dep_changes = risk.get("dependency_changes", False)
    lines += [
        "## Risk Metadata",
        "",
        f"- Lines changed: {lines_changed}",
        f"- Test ratio: {test_ratio:.0%}",
        f"- Dependency changes: {'Yes' if dep_changes else 'No'}",
    ]
    if high_risk:
        lines.append(f"- High-risk paths: {', '.join(f'`{p}`' for p in high_risk)}")
    lines.append("")

    leads = workflow_output.get("lead_outputs") or []
    specialists = workflow_output.get("specialist_outputs") or []

    if leads:
        lines += ["## Lead Findings", ""]
        for lead in leads:
            persona = lead.get("persona", "?")
            relevance = lead.get("domain_relevance", 0.0)
            confidence_l = lead.get("self_confidence", 0.0)
            findings = lead.get("findings") or []
            summary = lead.get("summary", "")
            lines += [
                f"### {persona}",
                f"relevance {relevance:.2f}  ·  confidence {confidence_l:.2f}",
                "",
            ]
            if summary:
                lines += [summary, ""]
            if findings:
                for f in findings:
                    sev = f.get("severity", "?")
                    loc = f.get("location", "")
                    desc = f.get("description", "")
                    impact = f.get("threat_or_impact", "")
                    loc_str = f" `{loc}`" if loc else ""
                    lines.append(f"**[{sev.upper()}]**{loc_str} {desc}")
                    if impact:
                        lines.append(f"  > {impact}")
            else:
                lines.append("_No findings._")
            lines.append("")

    if specialists:
        lines += ["## Specialist Findings", ""]
        for spec in specialists:
            persona = spec.get("persona", "?")
            findings = spec.get("findings") or []
            if not findings:
                continue
            lines += [f"### {persona}", ""]
            for f in findings:
                sev = f.get("severity", "?")
                loc = f.get("location", "")
                desc = f.get("description", "")
                impact = f.get("threat_or_impact", "")
                loc_str = f" `{loc}`" if loc else ""
                lines.append(f"**[{sev.upper()}]**{loc_str} {desc}")
                if impact:
                    lines.append(f"  > {impact}")
            lines.append("")

    if disagreements:
        lines += ["## Unresolved Disagreements", ""]
        for d in disagreements:
            lines += [
                f"- **{d.get('persona_a')}**: {d.get('concern_a')}",
                f"  vs **{d.get('persona_b')}**: {d.get('counter_b')}",
            ]
        lines.append("")

    return "\n".join(lines)
