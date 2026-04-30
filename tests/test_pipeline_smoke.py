"""End-to-end logical smoke test.

Exercises the data flow across all four services without Redis/Postgres:
    1. ingress: build RawEvent from a CLI-style payload
    2. core: classify → TaskSpec
    3. agents: run pr_review workflow with the Anthropic client mocked
    4. egress: render summary, dispatch to a stub deliverer

The Anthropic mock dispatches canned JSON responses based on the system
prompt in the call (each persona has a unique prompt header), simulating
the dispatcher → leads → CTO chain.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent_secretary_schemas import (
    ChannelTarget,
    RawEvent,
    ResponseRouting,
    ResultEvent,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = REPO_ROOT / "prompts"


# --- helpers ---------------------------------------------------------------


def _build_pr_event(**overrides) -> RawEvent:
    pr = {
        "number": 42,
        "title": "fix: tighten input validation in /api/items",
        "description": "Adds parameterized query and a regression test.",
        "author": "alice",
        "head_sha": "abc123",
        "base_sha": "def456",
        "url": "https://example.test/pr/42",
        "changed_files": ["api/items.py", "tests/test_items.py"],
        "diff_stats": {"additions": 30, "deletions": 5, "files_changed": 2},
        "diff": "--- a/api/items.py\n+++ b/api/items.py\n@@\n+# fix\n",
    }
    pr.update(overrides)
    return RawEvent(
        event_id=str(uuid.uuid4()),
        source_channel="cli",
        received_at=datetime.now(UTC),
        raw_payload={},
        normalized={
            "trigger": "manual",
            "repo": {"full_name": "acme/widgets"},
            "pr": pr,
        },
        response_routing=ResponseRouting(
            primary=ChannelTarget(channel="cli", target={"event_id_echo": True})
        ),
    )


def _fenced(payload: dict) -> str:
    return f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"


def _persona_for_system(system_prompt: str) -> str:
    """Identify which persona is being called from its system prompt header."""
    head = system_prompt.lstrip().splitlines()[0] if system_prompt else ""
    if "디스패처" in head or "dispatcher" in head.lower():
        return "dispatcher"
    if "CTO" in head:
        return "cto"
    if "보안 lead" in head:
        return "security_lead"
    if "품질 lead" in head:
        return "quality_lead"
    if "운영 lead" in head:
        return "ops_lead"
    if "호환성 lead" in head:
        return "compatibility_lead"
    if "제품·UX lead" in head:
        return "product_ux_lead"
    return "unknown"


def _build_anthropic_mock(canned: dict[str, dict]) -> SimpleNamespace:
    """Mock that returns canned JSON based on which persona is being called."""

    async def create(*, model, max_tokens, system, messages):
        persona = _persona_for_system(system)
        if persona not in canned:
            raise AssertionError(f"no canned response for persona={persona!r}")
        text = _fenced(canned[persona])
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=100, output_tokens=200),
        )

    return SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=create)))


def _settings():
    from agents.config import Settings

    return Settings(
        redis_url="redis://x",
        database_url=None,
        anthropic_api_key="dummy",
        log_level="WARNING",
        consumer_group="t",
        consumer_name="t1",
        prompts_dir=str(PROMPTS_DIR),
        model_cto="claude-opus-4-7",
        model_default="claude-sonnet-4-6",
        report_base_url=None,
    )


# --- canned responses ------------------------------------------------------


def _clean_lead(persona_name: str, domain: str) -> dict:
    return {
        "persona": persona_name,
        "domain": domain,
        "domain_relevance": 0.6,
        "self_confidence": 0.85,
        "findings": [],
        "summary": "변경은 기존 패턴을 따르고 우려 없음.",
        "unresolved_specialist_dissent": [],
    }


def _dispatcher_default() -> dict:
    return {
        "activated_leads": [
            {"name": "보안", "tier": 1, "reason": "always-on"},
            {"name": "품질", "tier": 1, "reason": "always-on"},
            {"name": "운영", "tier": 1, "reason": "always-on"},
        ],
        "activated_specialists": [],
        "skipped_specialists_with_reason": [],
        "ambiguous_decisions": [],
        "dispatcher_confidence": 0.95,
    }


# --- tests -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_clean_pr_routes_auto_merge():
    from agents.summary import render_summary_markdown
    from agents.workflows.pr_review import PrReviewRunner
    from core.classifier import classify
    from egress.plugins.cli import CliDeliverer

    event = _build_pr_event()
    [task] = classify(event)
    assert task.workflow == "pr_review"

    cto_clean = {
        "decision": "auto-merge",
        "confidence": 0.9,
        "reasoning": "모든 lead 가 우려 없이 통과, 위험 경로 없음.",
        "trigger_signals": [],
        "unresolved_disagreements": [],
        "risk_metadata": {
            "high_risk_paths_touched": [],
            "lines_changed": 35,
            "test_ratio": 0.5,
            "dependency_changes": False,
        },
    }
    canned = {
        "dispatcher": _dispatcher_default(),
        "security_lead": _clean_lead("보안 lead", "security"),
        "quality_lead": _clean_lead("품질 lead", "quality"),
        "ops_lead": _clean_lead("운영 lead", "ops"),
        "cto": cto_clean,
    }
    client = _build_anthropic_mock(canned)

    runner = PrReviewRunner(client, _settings())
    output = await runner.run(task.workflow_input)

    assert output["cto_output"]["decision"] == "auto-merge"
    assert len(output["lead_outputs"]) == 3

    result = ResultEvent(
        result_id=str(uuid.uuid4()),
        task_id=task.task_id,
        event_id=task.event_id,
        workflow=task.workflow,
        output=output,
        summary_markdown=render_summary_markdown(output),
        response_routing=task.response_routing,
        completed_at=datetime.now(UTC),
    )
    await CliDeliverer().deliver(result)


@pytest.mark.asyncio
async def test_pipeline_blocking_finding_routes_escalate():
    from agents.workflows.pr_review import PrReviewRunner
    from core.classifier import classify

    event = _build_pr_event(changed_files=["auth/session.py"])
    [task] = classify(event)

    security_blocking = {
        "persona": "보안 lead",
        "domain": "security",
        "domain_relevance": 0.95,
        "self_confidence": 0.85,
        "findings": [
            {
                "severity": "blocking",
                "location": "auth/session.py:42",
                "description": "토큰 만료 검사 누락",
                "threat_or_impact": "공격자가 만료된 세션을 재사용 가능",
            }
        ],
        "summary": "blocking 결함 발견.",
        "unresolved_specialist_dissent": [],
    }
    cto_escalate = {
        "decision": "escalate-to-human",
        "confidence": 0.4,
        "reasoning": "보안 lead 가 blocking finding 보고. 자동 머지 후보에서 제외.",
        "trigger_signals": [
            "보안 lead blocking (auth/session.py)",
            "high-risk paths: auth/",
        ],
        "unresolved_disagreements": [],
        "risk_metadata": {
            "high_risk_paths_touched": ["auth/"],
            "lines_changed": 35,
            "test_ratio": 0.0,
            "dependency_changes": False,
        },
    }
    canned = {
        "dispatcher": _dispatcher_default(),
        "security_lead": security_blocking,
        "quality_lead": _clean_lead("품질 lead", "quality"),
        "ops_lead": _clean_lead("운영 lead", "ops"),
        "cto": cto_escalate,
    }
    client = _build_anthropic_mock(canned)

    runner = PrReviewRunner(client, _settings())
    output = await runner.run(task.workflow_input)

    assert output["cto_output"]["decision"] == "escalate-to-human"
    assert any("blocking" in t.lower() for t in output["cto_output"]["trigger_signals"])
    assert "auth/" in output["risk_metadata"]["high_risk_paths_touched"]


def test_classifier_rejects_unknown_trigger():
    from core.classifier import UnclassifiedEvent, classify

    event = _build_pr_event()
    event.normalized["trigger"] = "unsupported_thing"
    with pytest.raises(UnclassifiedEvent):
        classify(event)


def test_classifier_ab_mode_emits_shadow_monolithic_task():
    from agent_secretary_config import (
        WORKFLOW_PR_REVIEW,
        WORKFLOW_PR_REVIEW_MONOLITHIC,
    )
    from core.classifier import classify

    event = _build_pr_event()

    # Default off → 1 task.
    tasks = classify(event)
    assert [t.workflow for t in tasks] == [WORKFLOW_PR_REVIEW]
    assert tasks[0].shadow is False

    # ab_mode → 2 tasks: primary visible + monolithic shadow.
    tasks = classify(event, ab_mode=True)
    assert [t.workflow for t in tasks] == [
        WORKFLOW_PR_REVIEW,
        WORKFLOW_PR_REVIEW_MONOLITHIC,
    ]
    assert tasks[0].shadow is False
    assert tasks[1].shadow is True
    # Both share event_id (used to JOIN traces for A/B comparison).
    assert tasks[0].event_id == tasks[1].event_id
    # But have distinct task_ids (so trace store treats them as separate rows).
    assert tasks[0].task_id != tasks[1].task_id


def test_classifier_ab_mode_does_not_double_slack_workflows():
    """A/B applies only to PR review. Slack-triggered workflows stay 1:1."""
    from agent_secretary_config import WORKFLOW_CODE_ANALYZE
    from core.classifier import classify

    event = _build_pr_event()
    # Force-make this look like a Slack mention event.
    event.normalized["trigger"] = "slack_mention"
    event.normalized["workflow"] = WORKFLOW_CODE_ANALYZE

    tasks = classify(event, ab_mode=True)
    assert len(tasks) == 1
    assert tasks[0].workflow == WORKFLOW_CODE_ANALYZE
    assert tasks[0].shadow is False


def test_trace_url_construction():
    """The agents service constructs trace_url only when both report_base_url
    and detail_markdown are present. Verify the formula in isolation."""
    base = "https://agent-secretary.example.com"
    task_id = "abc123"

    # Logic mirror of services/agents/agents/main.py
    def construct(rb: str | None, detail: str | None) -> str | None:
        if rb and detail:
            return f"{rb.rstrip('/')}/static/reports/{task_id}"
        return None

    assert construct(base, "x") == f"{base}/static/reports/{task_id}"
    assert construct(base + "/", "x") == f"{base}/static/reports/{task_id}"  # trailing-slash safe
    assert construct(None, "x") is None
    assert construct(base, None) is None
    assert construct(None, None) is None


@pytest.mark.asyncio
async def test_pipeline_with_quality_config_separation_specialist():
    """Source-code PR activates 설정 분리 specialist; quality lead receives its output."""
    from agents.workflows.pr_review import PrReviewRunner
    from core.classifier import classify

    event = _build_pr_event(
        changed_files=["src/clients/scheduler.py"],
        title="feat: add scheduled-job worker",
    )
    [task] = classify(event)

    dispatcher_with_quality_specialist = {
        "activated_leads": [
            {"name": "보안", "tier": 1, "reason": "always-on"},
            {"name": "품질", "tier": 1, "reason": "always-on"},
            {"name": "운영", "tier": 1, "reason": "always-on"},
        ],
        "activated_specialists": [
            {
                "name": "설정 분리",
                "lead": "품질",
                "trigger_type": "hard",
                "trigger_evidence": "src/clients/scheduler.py — Python 소스 변경",
                "reasoning": "비비즈니스 모듈에 매직 넘버 도입 가능",
            }
        ],
        "skipped_specialists_with_reason": [],
        "ambiguous_decisions": [],
        "dispatcher_confidence": 0.92,
    }
    config_specialist_output = {
        "persona": "설정 분리",
        "domain": "quality",
        "domain_relevance": 0.85,
        "self_confidence": 0.8,
        "findings": [
            {
                "severity": "warning",
                "location": "src/clients/scheduler.py:23",
                "description": "WORKER_TIMEOUT 매직 넘버. agent_secretary_config 로 이동 권장.",
                "threat_or_impact": "환경별 튜닝 시 변경 지점이 분산.",
            }
        ],
        "summary": "매직 넘버 1건.",
    }
    cto_clean = {
        "decision": "auto-merge",
        "confidence": 0.82,
        "reasoning": "warning 1건 (config 분리 권장) 외 특이사항 없음.",
        "trigger_signals": [],
        "unresolved_disagreements": [],
        "risk_metadata": {
            "high_risk_paths_touched": [],
            "lines_changed": 35,
            "test_ratio": 0.5,
            "dependency_changes": False,
        },
    }

    called: list[str] = []

    async def create(*, model, max_tokens, system, messages):
        persona = _persona_for_system(system)
        if persona == "unknown":
            head = system.lstrip().splitlines()[0]
            if "설정 분리" in head:
                persona = "config_separation"
        called.append(persona)
        canned = {
            "dispatcher": dispatcher_with_quality_specialist,
            "security_lead": _clean_lead("보안 lead", "security"),
            "quality_lead": _clean_lead("품질 lead", "quality"),
            "ops_lead": _clean_lead("운영 lead", "ops"),
            "config_separation": config_specialist_output,
            "cto": cto_clean,
        }
        if persona not in canned:
            raise AssertionError(f"no canned response for persona={persona!r}")
        text = _fenced(canned[persona])
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=100, output_tokens=200),
        )

    client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(side_effect=create))
    )
    runner = PrReviewRunner(client, _settings())
    output = await runner.run(task.workflow_input)

    assert "config_separation" in called
    assert "quality_lead" in called
    assert any(s["persona"] == "설정 분리" for s in output["specialist_outputs"])


@pytest.mark.asyncio
async def test_pipeline_with_specialist_activation():
    """Migration PR activates DB·migrations specialist; ops lead receives its output."""
    from agents.workflows.pr_review import PrReviewRunner
    from core.classifier import classify

    event = _build_pr_event(
        changed_files=["migrations/2026_04_30_add_idx.sql", "src/db.py"],
        title="feat: add user_email index",
    )
    [task] = classify(event)

    dispatcher_with_specialist = {
        "activated_leads": [
            {"name": "보안", "tier": 1, "reason": "always-on"},
            {"name": "품질", "tier": 1, "reason": "always-on"},
            {"name": "운영", "tier": 1, "reason": "always-on"},
        ],
        "activated_specialists": [
            {
                "name": "DB·마이그레이션",
                "lead": "운영",
                "trigger_type": "hard",
                "trigger_evidence": "migrations/ 디렉토리 변경",
                "reasoning": "migrations 파일 패턴 매칭",
            }
        ],
        "skipped_specialists_with_reason": [],
        "ambiguous_decisions": [],
        "dispatcher_confidence": 0.9,
    }

    db_specialist_output = {
        "persona": "DB·마이그레이션",
        "domain": "ops",
        "domain_relevance": 0.95,
        "self_confidence": 0.85,
        "findings": [],
        "summary": "신규 인덱스 추가만으로 가역성 OK.",
    }
    cto_clean = {
        "decision": "auto-merge",
        "confidence": 0.88,
        "reasoning": "마이그레이션은 idx 추가뿐, 위험 없음.",
        "trigger_signals": [],
        "unresolved_disagreements": [],
        "risk_metadata": {
            "high_risk_paths_touched": ["migrations/"],
            "lines_changed": 35,
            "test_ratio": 0.0,
            "dependency_changes": False,
        },
    }

    # Track which personas got called
    called_personas: list[str] = []

    async def create(*, model, max_tokens, system, messages):
        persona = _persona_for_system(system)
        if persona == "unknown":
            # try specialist matching: look for "DB·마이그레이션 specialist" header
            head = system.lstrip().splitlines()[0]
            if "DB·마이그레이션" in head:
                persona = "db_migrations"
        called_personas.append(persona)

        canned = {
            "dispatcher": dispatcher_with_specialist,
            "security_lead": _clean_lead("보안 lead", "security"),
            "quality_lead": _clean_lead("품질 lead", "quality"),
            "ops_lead": _clean_lead("운영 lead", "ops"),
            "db_migrations": db_specialist_output,
            "cto": cto_clean,
        }
        if persona not in canned:
            raise AssertionError(f"no canned response for persona={persona!r}")
        text = _fenced(canned[persona])
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=100, output_tokens=200),
        )

    client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(side_effect=create))
    )
    runner = PrReviewRunner(client, _settings())
    output = await runner.run(task.workflow_input)

    assert "db_migrations" in called_personas
    assert "ops_lead" in called_personas
    assert any(s["persona"] == "DB·마이그레이션" for s in output["specialist_outputs"])
    assert output["cto_output"]["decision"] == "auto-merge"
