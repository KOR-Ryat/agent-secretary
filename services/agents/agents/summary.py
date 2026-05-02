"""Channel-agnostic summary markdown generation for ResultEvent.

Egress plugins receive `summary_markdown` already and can use it directly,
trimming or wrapping per channel constraints.
"""

from __future__ import annotations

from typing import Any

_SEV_BADGE = {
    "P0": "🔴 P0",
    "P1": "🟠 P1",
    "P2": "🟡 P2",
    "P3": "🔵 P3",
    "P4": "⚪ P4",
}


def _sev_badge(sev: str) -> str:
    return _SEV_BADGE.get(sev.upper(), sev.upper())


def render_summary_markdown(workflow_output: dict[str, Any]) -> str:
    cto = workflow_output.get("cto_output", {})
    decision = cto.get("decision", "?")
    confidence = cto.get("confidence", 0.0)
    reasoning = cto.get("reasoning", "")

    lines = [
        "## 🤖 agent-secretary",
        "",
        f"`{decision}`  ·  confidence {confidence:.2f}",
        "",
    ]

    # P0/P1 findings only
    critical_findings: list[str] = []
    for lead in (workflow_output.get("lead_outputs") or []):
        for f in (lead.get("findings") or []):
            sev = f.get("severity", "")
            if sev in ("P0", "P1"):
                loc = f.get("location", "")
                desc = f.get("description", "")
                loc_str = f" `{loc}`" if loc else ""
                critical_findings.append(f"- [{sev}]{loc_str} — {desc}")

    if critical_findings:
        lines.append("**P0/P1 findings:**")
        lines.extend(critical_findings)
        lines.append("")

    if reasoning:
        lines.append(f"**요약:** {reasoning}")
        lines.append("")

    return "\n".join(lines)


def _render_findings(findings: list[dict[str, Any]]) -> list[str]:
    """Render a list of findings as markdown blocks."""
    lines: list[str] = []
    for f in findings:
        sev = f.get("severity", "?")
        loc = f.get("location", "")
        desc = f.get("description", "")
        impact = f.get("threat_or_impact", "")
        suggestion = f.get("suggestion", "")

        badge = _sev_badge(sev)
        loc_str = f" — `{loc}`" if loc else ""
        lines.append(f"**{badge}**{loc_str}")
        lines.append(f"{desc}")
        if impact:
            lines.append(f"> **영향:** {impact}")
        if suggestion:
            lines.append(f"> **제안:** {suggestion}")
        lines.append("")
    return lines


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
        f"**결정:** `{decision}`  ·  **신뢰도:** {confidence:.2f}",
        "",
    ]

    if reasoning:
        lines += [f"> {reasoning}", ""]

    lines.append("---")
    lines.append("")

    # Risk summary
    high_risk = risk.get("high_risk_paths_touched") or []
    lines_changed = risk.get("lines_changed", 0)
    test_ratio = risk.get("test_ratio", 0.0)
    dep_changes = risk.get("dependency_changes", False)
    risk_parts = [
        f"변경 라인 **{lines_changed}**",
        f"테스트 비율 **{test_ratio:.0%}**",
        f"의존성 변경 **{'Yes' if dep_changes else 'No'}**",
    ]
    if high_risk:
        risk_parts.append(f"고위험 경로 {', '.join(f'`{p}`' for p in high_risk)}")
    lines += ["## 위험 요약", "", "  ·  ".join(risk_parts), ""]

    if triggers:
        lines += ["**트리거 신호:**", ""]
        lines += [f"- {t}" for t in triggers]
        lines.append("")

    lines.append("---")
    lines.append("")

    # Build specialist lookup by lead name
    specialists = workflow_output.get("specialist_outputs") or []
    specs_by_lead: dict[str, list[dict[str, Any]]] = {}
    for spec in specialists:
        lead_name = spec.get("lead_name", "")
        specs_by_lead.setdefault(lead_name, []).append(spec)

    leads = workflow_output.get("lead_outputs") or []

    if leads:
        lines += ["## 리뷰 결과", ""]
        for lead in leads:
            persona = lead.get("persona", "?")
            relevance = lead.get("domain_relevance", 0.0)
            confidence_l = lead.get("self_confidence", 0.0)
            lead_findings = lead.get("findings") or []
            summary = lead.get("summary", "")

            # Count by severity for the lead header
            sev_counts: dict[str, int] = {}
            for f in lead_findings:
                s = f.get("severity", "?").upper()
                sev_counts[s] = sev_counts.get(s, 0) + 1
            sev_summary = "  ".join(
                f"{_sev_badge(s)} ×{n}" for s, n in sorted(sev_counts.items())
            ) if sev_counts else "findings 없음"

            lines += [
                f"### {persona}",
                f"관련도 {relevance:.2f}  ·  신뢰도 {confidence_l:.2f}  ·  {sev_summary}",
                "",
            ]

            if summary:
                lines += [summary, ""]

            if lead_findings:
                # P0/P1 first, then rest
                blocking = [f for f in lead_findings if f.get("severity", "") in ("P0", "P1")]
                rest = [f for f in lead_findings if f.get("severity", "") not in ("P0", "P1")]
                if blocking:
                    lines.append("**블로킹 이슈:**")
                    lines.append("")
                    lines.extend(_render_findings(blocking))
                if rest:
                    if blocking:
                        lines.append("**기타 findings:**")
                        lines.append("")
                    lines.extend(_render_findings(rest))
            else:
                lines += ["_findings 없음._", ""]

            # Inline specialists under this lead
            lead_specs = specs_by_lead.get(persona, [])
            if not lead_specs:
                # Try matching by lead field inside specialist output
                lead_specs = [s for s in specialists if s.get("lead_name") == persona]
            for spec in lead_specs:
                spec_persona = spec.get("persona", "?")
                spec_findings = spec.get("findings") or []
                if not spec_findings:
                    continue
                lines += [f"#### ↳ {spec_persona}", ""]
                lines.extend(_render_findings(spec_findings))

            lines.append("---")
            lines.append("")

    if disagreements:
        lines += ["## 의견 충돌", ""]
        for d in disagreements:
            lines += [
                f"- **{d.get('persona_a')}:** {d.get('concern_a')}",
                f"  **{d.get('persona_b')}:** {d.get('counter_b')}",
                "",
            ]

    return "\n".join(lines)
