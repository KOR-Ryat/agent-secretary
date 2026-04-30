"""Dashboard tests.

Verifies:
  - GET /  serves the static index.html
  - /api/traces returns 503 when DB unconfigured
  - /api/traces returns the rows yielded by an injected TraceReader
  - /api/traces/{task_id} returns the row, or 404 if missing
  - /api/stats/decisions returns aggregate KPIs
  - /api/stats/decisions rejects unknown range tokens
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock


def _make_app(trace_reader=None):
    from fastapi import FastAPI
    from ingress.dashboard.routes import register_dashboard

    app = FastAPI()
    register_dashboard(app, trace_reader)
    return app


def test_index_html_is_served():
    from fastapi.testclient import TestClient

    app = _make_app(trace_reader=None)
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    assert "agent-secretary" in res.text


def test_api_traces_503_when_no_db():
    from fastapi.testclient import TestClient

    app = _make_app(trace_reader=None)
    client = TestClient(app)
    res = client.get("/api/traces")
    assert res.status_code == 503
    assert "DATABASE_URL" in res.json()["error"]


def test_api_traces_lists_rows():
    from fastapi.testclient import TestClient

    rows = [
        {
            "task_id": "t1",
            "event_id": "e1",
            "workflow": "pr_review",
            "source_channel": "github",
            "summary_markdown": "ok",
            "decision": "auto-merge",
            "confidence": "0.92",
            "completed_at": datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
            "created_at": datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
        },
    ]

    reader = AsyncMock()
    reader.list_recent.return_value = rows

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/traces?limit=10")
    assert res.status_code == 200
    body = res.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["task_id"] == "t1"
    # datetime serialized to ISO string
    assert body["items"][0]["completed_at"].startswith("2026-04-30T12:00")


def test_api_trace_detail_404_when_missing():
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.get.return_value = None

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/traces/missing")
    assert res.status_code == 404


def test_api_stats_decisions_503_when_no_db():
    from fastapi.testclient import TestClient

    app = _make_app(trace_reader=None)
    client = TestClient(app)
    res = client.get("/api/stats/decisions?range=24h")
    assert res.status_code == 503


def test_api_stats_decisions_returns_aggregate():
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.stats_decisions.return_value = {
        "range": "24h",
        "total": 10,
        "auto_merge": 6,
        "request_changes": 2,
        "escalate": 1,
        "no_decision": 1,
        "escalation_rate": 0.1,
        "avg_confidence": 0.83,
    }

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/stats/decisions?range=24h")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 10
    assert body["auto_merge"] == 6
    assert body["escalation_rate"] == 0.1
    reader.stats_decisions.assert_awaited_once_with("24h")


def test_api_stats_decisions_rejects_invalid_range():
    """Unknown range tokens must 400 — never reach the SQL layer."""
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/stats/decisions?range=nope")
    assert res.status_code == 400
    reader.stats_decisions.assert_not_awaited()


def test_api_stats_decisions_default_range_is_24h():
    """No range param → defaults to 24h (sensible recent-activity window)."""
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.stats_decisions.return_value = {
        "range": "24h", "total": 0, "auto_merge": 0,
        "request_changes": 0, "escalate": 0, "no_decision": 0,
        "escalation_rate": 0.0, "avg_confidence": None,
    }

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/stats/decisions")
    assert res.status_code == 200
    reader.stats_decisions.assert_awaited_once_with("24h")


def test_api_trace_detail_returns_row():
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.get.return_value = {
        "task_id": "t1",
        "event_id": "e1",
        "workflow": "pr_review",
        "source_channel": "github",
        "pr_metadata": {"title": "fix"},
        "dispatcher_output": None,
        "specialist_outputs": None,
        "lead_outputs": None,
        "cto_output": {"decision": "auto-merge"},
        "risk_metadata": None,
        "summary_markdown": "ok",
        "detail_markdown": None,
        "human_decision": None,
        "created_at": datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
        "completed_at": datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
    }

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/traces/t1")
    assert res.status_code == 200
    data = res.json()
    assert data["task_id"] == "t1"
    assert data["cto_output"]["decision"] == "auto-merge"
