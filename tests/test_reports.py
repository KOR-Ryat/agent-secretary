"""Tests for /static/reports/{task_id} markdown viewer."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock


def _make_app(trace_reader):
    from fastapi import FastAPI
    from ingress.dashboard.reports import register_reports

    app = FastAPI()
    register_reports(app, trace_reader)
    return app


def _row(*, detail: str | None = None, decision: str = "auto-merge") -> dict:
    return {
        "task_id": "t1",
        "event_id": "e1",
        "workflow": "code_analyze",
        "source_channel": "slack",
        "summary_markdown": "summary",
        "detail_markdown": detail,
        "cto_output": {"decision": decision} if decision else None,
        "created_at": datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
        "completed_at": datetime(2026, 4, 30, 12, 1, tzinfo=UTC),
    }


def test_html_renders_markdown_to_styled_page():
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.get.return_value = _row(
        detail="# Title\n\nSome **bold** text.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
    )

    client = TestClient(_make_app(reader))
    res = client.get("/static/reports/t1")
    assert res.status_code == 200
    body = res.text
    # Markdown rendering happened.
    assert "<h1" in body and "Title" in body
    assert "<strong>bold</strong>" in body
    assert "<table>" in body
    # Wrapping page applied.
    assert "agent-secretary" in body
    assert "code_analyze" in body
    assert "auto-merge" in body
    # Raw markdown footer link uses the .md endpoint.
    assert '/static/reports/t1.md' in body


def test_raw_returns_markdown_text():
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.get.return_value = _row(detail="# Heading\n\nbody")

    client = TestClient(_make_app(reader))
    res = client.get("/static/reports/t1.md")
    assert res.status_code == 200
    assert res.text == "# Heading\n\nbody"
    assert "text/markdown" in res.headers.get("content-type", "")


def test_404_when_task_id_unknown():
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.get.return_value = None

    client = TestClient(_make_app(reader))
    assert client.get("/static/reports/missing").status_code == 404
    assert client.get("/static/reports/missing.md").status_code == 404


def test_404_when_detail_is_empty():
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.get.return_value = _row(detail=None)

    client = TestClient(_make_app(reader))
    res = client.get("/static/reports/t1")
    assert res.status_code == 404


def test_503_when_no_db():
    from fastapi.testclient import TestClient

    client = TestClient(_make_app(None))
    res = client.get("/static/reports/t1")
    assert res.status_code == 503
    assert "DATABASE_URL" in res.json()["detail"]


def test_decision_class_applied_to_html():
    """The `cto_output.decision` value is reflected in a CSS class for styling."""
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.get.return_value = _row(detail="x", decision="escalate-to-human")

    client = TestClient(_make_app(reader))
    body = client.get("/static/reports/t1").text
    assert 'class="decision escalate-to-human"' in body
