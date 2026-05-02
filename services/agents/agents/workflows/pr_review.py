"""PR review workflow.

Stage 1 — dispatcher decides which leads/specialists to activate.
Stage 2 — activated specialists run in parallel.
Stage 3 — activated leads run in parallel, each receiving its specialists' outputs.
Stage 4 — CTO synthesizes lead outputs into a 3-way decision.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from agent_secretary_config import (
    GitHubAppAuth,
    Repo,
    resolve_rules,
    review_rules_for,
)
from agent_secretary_schemas import PersonaOutput
from agent_secretary_schemas.personas import RiskMetadata

from agents.config import Settings
from agents.logging import get_logger
from agents.personas.cto import Cto
from agents.summary import render_detail_markdown
from agents.personas.dispatcher import Dispatcher
from agents.personas.registry import build_lead
from agents.personas.specialists.specialist_agent import (
    SPECIALIST_BY_NAME,
    build_specialist,
)
from agents.skills.workspace import WorkspaceManager, WorkspaceSettings

log = get_logger("agents.workflows.pr_review")


class PrReviewRunner:
    def __init__(self, settings: Settings) -> None:
        self._prompts = Path(settings.prompts_dir)
        self._model_default = settings.model_default
        self._dispatcher = Dispatcher(self._prompts, settings.model_default)
        self._cto = Cto(self._prompts, settings.model_cto)
        try:
            auth: GitHubAppAuth | None = GitHubAppAuth.from_env()
        except RuntimeError:
            auth = None
        try:
            ws_settings = WorkspaceSettings.from_env()
            self._workspace: WorkspaceManager | None = WorkspaceManager(ws_settings, auth)
        except RuntimeError:
            self._workspace = None

    async def run(self, workflow_input: dict) -> dict:
        pr = workflow_input.get("pr", {})
        repo_full_name = (workflow_input.get("repo") or {}).get("full_name")
        installation_id = workflow_input.get("installation_id")
        log.info(
            "workflow.pr_review.start",
            pr_title=pr.get("title", "")[:60],
            repo=repo_full_name,
        )

        pr = await self._enrich_pr(pr, repo_full_name, installation_id)

        # Stage 1: dispatcher
        activation = await self._dispatcher.call({"pr": pr})
        activated_lead_names = [lead.name for lead in activation.activated_leads]
        activated_specialist_names = [s.name for s in activation.activated_specialists]
        log.info(
            "workflow.dispatcher.complete",
            activated_leads=activated_lead_names,
            activated_specialists=activated_specialist_names,
            confidence=activation.dispatcher_confidence,
        )

        # Stage 2: specialists in parallel (filtered to known + lead-activated)
        specialist_outputs_by_lead = await self._run_specialists(
            pr, activated_specialist_names, activated_lead_names
        )

        # Stage 3: leads in parallel, each with its specialist outputs
        lead_outputs = await self._run_leads(
            pr, activated_lead_names, specialist_outputs_by_lead
        )
        log.info("workflow.leads.complete", count=len(lead_outputs))

        # Stage 4: CTO
        risk_metadata = _compute_risk_metadata(pr, repo_full_name)
        cto_output = await self._cto.call(
            {
                "pr": pr,
                "dispatcher_output": activation.model_dump(),
                "lead_outputs": [o.model_dump() for o in lead_outputs],
                "risk_metadata": risk_metadata.model_dump(),
            }
        )
        log.info(
            "workflow.cto.complete",
            decision=cto_output.decision,
            confidence=cto_output.confidence,
        )

        # Flatten specialist outputs for trace store / debugging.
        all_specialist_outputs: list[dict[str, Any]] = []
        for lst in specialist_outputs_by_lead.values():
            all_specialist_outputs.extend(o.model_dump() for o in lst)

        output = {
            "dispatcher_output": activation.model_dump(),
            "specialist_outputs": all_specialist_outputs,
            "lead_outputs": [o.model_dump() for o in lead_outputs],
            "cto_output": cto_output.model_dump(),
            "risk_metadata": risk_metadata.model_dump(),
        }
        output["detail_markdown"] = render_detail_markdown(output)
        return output

    async def _run_specialists(
        self,
        pr: dict,
        activated_specialist_names: list[str],
        activated_lead_names: list[str],
    ) -> dict[str, list[PersonaOutput]]:
        # Build specialists, filtering out unknown ones and those whose lead
        # is not activated.
        runners: list[tuple[str, Any]] = []  # (lead_name, agent)
        for name in activated_specialist_names:
            spec = SPECIALIST_BY_NAME.get(name)
            if spec is None:
                log.warning("workflow.specialist.unknown", name=name)
                continue
            if spec.lead not in activated_lead_names:
                log.warning(
                    "workflow.specialist.lead_inactive",
                    specialist=name,
                    lead=spec.lead,
                )
                continue
            agent = build_specialist(name, self._prompts, self._model_default)
            assert agent is not None
            runners.append((spec.lead, agent))

        if not runners:
            return {}

        outputs = await asyncio.gather(
            *[agent.call({"pr": pr}) for _, agent in runners]
        )
        grouped: dict[str, list[PersonaOutput]] = defaultdict(list)
        for (lead_name, _), output in zip(runners, outputs, strict=True):
            grouped[lead_name].append(output)
        log.info(
            "workflow.specialists.complete",
            count=len(outputs),
            by_lead={k: len(v) for k, v in grouped.items()},
        )
        return dict(grouped)

    async def _run_leads(
        self,
        pr: dict,
        activated_lead_names: list[str],
        specialist_outputs_by_lead: dict[str, list[PersonaOutput]],
    ) -> list:
        leads = []
        for name in activated_lead_names:
            agent = build_lead(name, self._prompts, self._model_default)
            if agent is None:
                log.warning("workflow.lead.unknown", name=name)
                continue
            specialist_payloads = [
                {"persona": s.persona, "output": s.model_dump()}
                for s in specialist_outputs_by_lead.get(name, [])
            ]
            leads.append((name, agent, specialist_payloads))

        return await asyncio.gather(
            *[
                agent.call({"pr": pr, "specialist_outputs": payloads})
                for _, agent, payloads in leads
            ]
        )


    async def _fetch_pr_shas(self, pr: dict, repo: str, number: int) -> dict:
        """Fetch head_sha / base_sha from GitHub API when not in the payload."""
        import httpx
        try:
            token = await self._workspace._auth.get_token()
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"https://api.github.com/repos/{repo}/pulls/{number}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            return {
                **pr,
                "head_sha": data["head"]["sha"],
                "base_sha": data["base"]["sha"],
            }
        except Exception as e:
            log.warning("workflow.pr_review.fetch_shas.failed", error=str(e))
            return pr

    async def _enrich_pr(
        self,
        pr: dict,
        repo_full_name: str | None,
        installation_id: int | None,
    ) -> dict:
        """Fetch diff + changed files from a worktree and enrich the pr dict.

        Falls back to the original pr dict if workspace is unavailable or the
        fetch fails (no GitHub App creds, missing env, etc.).
        """
        if not self._workspace or not repo_full_name:
            log.warning("workflow.pr_review.enrich.skip", reason="no workspace or repo")
            return pr

        head_sha = pr.get("head_sha")
        base_sha = pr.get("base_sha")
        if not head_sha or not base_sha:
            pr_number = pr.get("number")
            if pr_number and self._workspace._auth:
                pr = await self._fetch_pr_shas(pr, repo_full_name, pr_number)
                head_sha = pr.get("head_sha")
                base_sha = pr.get("base_sha")
        if not head_sha or not base_sha:
            log.warning("workflow.pr_review.enrich.skip", reason="missing head/base sha")
            return pr

        repo = Repo(name=repo_full_name, production="main", staging="main", dev="main")
        session_id = uuid.uuid4().hex[:8]
        log.info("workflow.pr_review.enrich.start", repo=repo_full_name, session_id=session_id)
        try:
            async with self._workspace.mount(repo, head_sha, session_id) as wt:
                diff = await self._workspace._git_capture(
                    "-C", str(wt), "diff", f"{base_sha}..{head_sha}"
                )
                names_out = await self._workspace._git_capture(
                    "-C", str(wt), "diff", "--name-only", f"{base_sha}..{head_sha}"
                )
                numstat_out = await self._workspace._git_capture(
                    "-C", str(wt), "diff", "--numstat", f"{base_sha}..{head_sha}"
                )
        except Exception as e:
            log.warning("workflow.pr_review.enrich.failed", error=str(e))
            return pr

        changed_files = [f for f in names_out.splitlines() if f]
        additions = deletions = 0
        for line in numstat_out.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                try:
                    additions += int(parts[0])
                    deletions += int(parts[1])
                except ValueError:
                    pass

        log.info(
            "workflow.pr_review.enrich.done",
            files=len(changed_files),
            additions=additions,
            deletions=deletions,
        )
        return {
            **pr,
            "diff": diff,
            "changed_files": changed_files,
            "diff_stats": {"additions": additions, "deletions": deletions},
        }


def _compute_risk_metadata(
    pr: dict[str, Any],
    repo_full_name: str | None = None,
) -> RiskMetadata:
    """Deterministic risk metadata.

    Pattern lists come from `agent_secretary_config` — per-repo overrides
    declared in `service_map.SERVICE_MAP[*].repos[*].review_rules` take
    precedence over module defaults; absent fields fall back.
    """
    rules = resolve_rules(review_rules_for(repo_full_name))
    changed_files = pr.get("changed_files") or []

    high_risk_paths_touched: list[str] = []
    for path in changed_files:
        for tag in rules.high_risk_paths:
            if tag in path and tag not in high_risk_paths_touched:
                high_risk_paths_touched.append(tag)

    stats = pr.get("diff_stats") or {}
    lines_changed = int(stats.get("additions", 0)) + int(stats.get("deletions", 0))

    test_files = sum(
        1
        for p in changed_files
        if any(m in p.lower() for m in rules.test_file_patterns)
    )
    test_ratio = test_files / len(changed_files) if changed_files else 0.0

    dependency_changes = any(
        any(marker in p for marker in rules.dependency_file_patterns)
        for p in changed_files
    )

    return RiskMetadata(
        high_risk_paths_touched=high_risk_paths_touched,
        lines_changed=lines_changed,
        test_ratio=test_ratio,
        dependency_changes=dependency_changes,
    )
