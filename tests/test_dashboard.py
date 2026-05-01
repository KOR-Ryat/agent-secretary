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


def _make_app(trace_reader=None, queue_health=None):
    from fastapi import FastAPI
    from ingress.dashboard.routes import register_dashboard

    app = FastAPI()
    register_dashboard(app, trace_reader, queue_health)
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


def test_api_traces_passes_filters_through():
    """decision / workflow / range filters reach list_recent intact."""
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.list_recent.return_value = []

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get(
        "/api/traces?decision=auto-merge&workflow=pr_review&range=24h"
    )
    assert res.status_code == 200
    reader.list_recent.assert_awaited_once_with(
        limit=50,
        offset=0,
        decision="auto-merge",
        workflow="pr_review",
        range_token="24h",
        q=None,
    )


def test_api_traces_rejects_unknown_filter_values():
    """Unknown filters → 400 before touching the reader."""
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    app = _make_app(trace_reader=reader)
    client = TestClient(app)

    for url in (
        "/api/traces?decision=BOGUS",
        "/api/traces?workflow=not-a-workflow",
        "/api/traces?range=99y",
    ):
        res = client.get(url)
        assert res.status_code == 400, url
    reader.list_recent.assert_not_awaited()


def test_api_traces_search_param_passes_through():
    """q is forwarded as range_token sibling, with whitespace stripped."""
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.list_recent.return_value = []

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/traces?q=  mesher-labs/project-201  ")
    assert res.status_code == 200
    reader.list_recent.assert_awaited_once_with(
        limit=50, offset=0,
        decision=None, workflow=None, range_token=None,
        q="mesher-labs/project-201",
    )


def test_api_traces_empty_search_treated_as_no_search():
    """?q= alone should not constrain — no SQL substring filter."""
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.list_recent.return_value = []

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/traces?q=")
    assert res.status_code == 200
    reader.list_recent.assert_awaited_once_with(
        limit=50, offset=0,
        decision=None, workflow=None, range_token=None,
        q=None,
    )


def test_build_list_sql_search_adds_three_ilike_params():
    """The OR(ilike) lookup binds the same %term% three times so callers
    don't have to construct the wildcard form themselves."""
    from ingress.dashboard.traces import _build_list_sql

    sql, params = _build_list_sql(
        decision=None, workflow=None, range_token=None, q="abc"
    )
    assert "ILIKE" in sql
    assert sql.count("ILIKE") == 3
    # First three params are the search term wildcards (LIMIT/OFFSET appended later).
    assert params == ["%abc%", "%abc%", "%abc%"]


def test_build_list_sql_no_filters():
    """No filters → no WHERE clause; just LIMIT/OFFSET parameters."""
    from ingress.dashboard.traces import _build_list_sql

    sql, params = _build_list_sql(decision=None, workflow=None, range_token=None)
    assert "WHERE" not in sql
    assert params == []


def test_build_list_sql_decision_none_uses_is_null():
    """The 'none' decision sentinel must translate to IS NULL — not bind
    the literal string 'none' as a JSON value (which would match nothing)."""
    from ingress.dashboard.traces import _build_list_sql

    sql, params = _build_list_sql(
        decision="none", workflow=None, range_token=None
    )
    assert "IS NULL" in sql
    assert "none" not in params


def test_build_list_sql_combined_filters():
    """Each filter contributes one bound parameter, in declaration order."""
    from ingress.dashboard.traces import _build_list_sql

    sql, params = _build_list_sql(
        decision="auto-merge", workflow="pr_review", range_token="24h"
    )
    assert sql.count("%s") == 5  # 3 filters + LIMIT + OFFSET
    assert params == ["auto-merge", "pr_review", "24 hours"]


def test_build_list_sql_range_all_skips_window():
    """range='all' is a sentinel for 'no time filter' — no interval bound."""
    from ingress.dashboard.traces import _build_list_sql

    sql, params = _build_list_sql(
        decision=None, workflow=None, range_token="all"
    )
    assert "interval" not in sql
    assert params == []


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


def test_api_health_queues_503_when_no_redis():
    """If queue_health isn't injected (e.g. dev without Redis), the
    endpoint must 503 — not 500 — so the UI can hide the card."""
    from fastapi.testclient import TestClient

    app = _make_app(trace_reader=None, queue_health=None)
    client = TestClient(app)
    res = client.get("/api/health/queues")
    assert res.status_code == 503


def test_api_health_queues_returns_snapshot():
    from fastapi.testclient import TestClient

    health = AsyncMock()
    health.snapshot.return_value = {
        "now_ms": 1700000000000,
        "total_depth": 5,
        "total_dlq": 1,
        "pairs": [
            {
                "live": {
                    "name": "raw_events",
                    "length": 3,
                    "oldest_age_seconds": 1.5,
                    "groups": [
                        {"name": "core", "pending": 2, "consumers": 1, "lag": 1},
                    ],
                },
                "dlq": {"name": "raw_events_dlq", "length": 0,
                        "oldest_age_seconds": None, "groups": []},
            },
            {
                "live": {
                    "name": "tasks", "length": 2, "oldest_age_seconds": 0.4,
                    "groups": [{"name": "agents", "pending": 0, "consumers": 1, "lag": 0}],
                },
                "dlq": {"name": "tasks_dlq", "length": 1,
                        "oldest_age_seconds": 600.0, "groups": []},
            },
            {
                "live": {"name": "results", "length": 0,
                         "oldest_age_seconds": None, "groups": []},
                "dlq": {"name": "results_dlq", "length": 0,
                        "oldest_age_seconds": None, "groups": []},
            },
        ],
    }

    app = _make_app(queue_health=health)
    client = TestClient(app)
    res = client.get("/api/health/queues")
    assert res.status_code == 200
    body = res.json()
    assert body["total_depth"] == 5
    assert body["total_dlq"] == 1
    # The DLQ with depth=1 is what an operator most needs to see.
    dlq_with_msg = body["pairs"][1]["dlq"]
    assert dlq_with_msg["name"] == "tasks_dlq"
    assert dlq_with_msg["length"] == 1
    health.snapshot.assert_awaited_once()


def test_api_health_queues_503_on_snapshot_failure():
    """Broker errors must not 500 — return 503 so the card stays hidden."""
    from fastapi.testclient import TestClient

    health = AsyncMock()
    health.snapshot.side_effect = RuntimeError("redis: connection refused")

    app = _make_app(queue_health=health)
    client = TestClient(app)
    res = client.get("/api/health/queues")
    assert res.status_code == 503
    assert "snapshot failed" in res.json()["error"]


def test_age_seconds_from_id_parses_redis_stream_id():
    from ingress.dashboard.health import _age_seconds_from_id

    # Stream ID format: <unix_ms>-<seq>
    age = _age_seconds_from_id("1700000000000-0", 1700000005000)
    assert age == 5.0


def test_age_seconds_from_id_handles_clock_skew():
    """If oldest entry's timestamp is *ahead* of now (clock skew), clamp
    to 0 instead of returning a negative number."""
    from ingress.dashboard.health import _age_seconds_from_id

    age = _age_seconds_from_id("1700000010000-0", 1700000005000)
    assert age == 0.0


def test_age_seconds_from_id_returns_none_for_garbage():
    from ingress.dashboard.health import _age_seconds_from_id

    assert _age_seconds_from_id("not-an-id", 0) is None
    assert _age_seconds_from_id("abc-xyz", 0) is None


def test_compare_page_serves_html():
    """The /compare/{event_id} page is static; the route must serve it
    so the SPA can fetch its data client-side."""
    from fastapi.testclient import TestClient

    app = _make_app(trace_reader=AsyncMock())
    client = TestClient(app)
    res = client.get("/compare/abc-123")
    assert res.status_code == 200
    assert "A/B compare" in res.text


def test_api_compare_404_when_no_traces():
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.list_ab_pair.return_value = []

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/compare/missing-event")
    assert res.status_code == 404


def test_api_compare_returns_pair_when_both_present():
    """list_ab_pair returns up to 2 rows; route splits them by workflow."""
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.list_ab_pair.return_value = [
        {
            "task_id": "tA", "event_id": "evt-1",
            "workflow": "pr_review", "source_channel": "github",
            "pr_metadata": {}, "dispatcher_output": None,
            "specialist_outputs": None, "lead_outputs": None,
            "cto_output": {"decision": "auto-merge", "confidence": 0.9},
            "risk_metadata": None, "summary_markdown": "A",
            "detail_markdown": None, "human_decision": None,
            "created_at": datetime(2026, 4, 30, 12, tzinfo=UTC),
            "completed_at": datetime(2026, 4, 30, 12, 1, tzinfo=UTC),
        },
        {
            "task_id": "tB", "event_id": "evt-1",
            "workflow": "pr_review_monolithic", "source_channel": "github",
            "pr_metadata": {}, "dispatcher_output": None,
            "specialist_outputs": None, "lead_outputs": None,
            "cto_output": {"decision": "request-changes", "confidence": 0.7},
            "risk_metadata": None, "summary_markdown": "B",
            "detail_markdown": None, "human_decision": None,
            "created_at": datetime(2026, 4, 30, 12, tzinfo=UTC),
            "completed_at": datetime(2026, 4, 30, 12, 2, tzinfo=UTC),
        },
    ]

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/compare/evt-1")
    assert res.status_code == 200
    body = res.json()
    assert body["primary"]["task_id"] == "tA"
    assert body["shadow"]["task_id"] == "tB"
    assert body["primary"]["cto_output"]["decision"] == "auto-merge"
    assert body["shadow"]["cto_output"]["decision"] == "request-changes"


def test_api_compare_handles_one_sided_pair():
    """If only the primary completed (shadow still in flight), the route
    must still 200 with shadow=None — not 404."""
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.list_ab_pair.return_value = [
        {
            "task_id": "tA", "event_id": "evt-2",
            "workflow": "pr_review", "source_channel": "github",
            "pr_metadata": {}, "dispatcher_output": None,
            "specialist_outputs": None, "lead_outputs": None,
            "cto_output": {"decision": "auto-merge"},
            "risk_metadata": None, "summary_markdown": None,
            "detail_markdown": None, "human_decision": None,
            "created_at": datetime(2026, 4, 30, 12, tzinfo=UTC),
            "completed_at": datetime(2026, 4, 30, 12, 1, tzinfo=UTC),
        },
    ]

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/compare/evt-2")
    assert res.status_code == 200
    body = res.json()
    assert body["primary"]["task_id"] == "tA"
    assert body["shadow"] is None


def test_api_stats_ab_returns_pairs():
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.stats_ab.return_value = {
        "range": "24h",
        "total_pairs": 3,
        "agree": 2,
        "disagree": 1,
        "agreement_rate": 2 / 3,
        "pairs": [
            {
                "event_id": "e1", "primary_task_id": "tp1", "shadow_task_id": "ts1",
                "primary_decision": "auto-merge", "shadow_decision": "auto-merge",
                "primary_confidence": "0.9", "shadow_confidence": "0.85",
                "created_at": datetime(2026, 4, 30, 11, tzinfo=UTC),
            },
        ],
    }

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/stats/ab?range=24h")
    assert res.status_code == 200
    body = res.json()
    assert body["total_pairs"] == 3
    assert body["disagree"] == 1
    assert len(body["pairs"]) == 1


def test_api_stats_ab_rejects_invalid_range():
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/stats/ab?range=zzz")
    assert res.status_code == 400
    reader.stats_ab.assert_not_awaited()


def test_api_stats_by_repo_returns_rows_with_escalation_rate():
    """by_repo computes escalation_rate per row from the SQL counts —
    keeps SQL portable while letting the UI stay shape-agnostic."""
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.stats_by_dimension.return_value = [
        {
            "dim": "mesher-labs/project-201-server",
            "total": 10,
            "auto_merge": 6,
            "request_changes": 3,
            "escalate": 1,
            "avg_confidence": 0.82,
        },
    ]

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/stats/by_repo?range=24h")
    assert res.status_code == 200
    body = res.json()
    assert body["dimension"] == "repo"
    assert body["range"] == "24h"
    assert body["items"][0]["escalation_rate"] == 0.1
    reader.stats_by_dimension.assert_awaited_once_with("repo", "24h", limit=20)


def test_api_stats_by_channel_uses_channel_dimension():
    """The /by_channel and /by_repo routes share an aggregator but pass
    different dimension tokens through."""
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.stats_by_dimension.return_value = []

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/stats/by_channel?range=7d&limit=5")
    assert res.status_code == 200
    reader.stats_by_dimension.assert_awaited_once_with("channel", "7d", limit=5)


def test_api_stats_by_repo_zero_total_doesnt_divide_by_zero():
    """If a row sneaks through with total=0 (shouldn't, but be safe),
    escalation_rate must be 0.0, not raise."""
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.stats_by_dimension.return_value = [
        {"dim": "x", "total": 0, "auto_merge": 0,
         "request_changes": 0, "escalate": 0, "avg_confidence": None},
    ]

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/stats/by_repo")
    assert res.status_code == 200
    assert res.json()["items"][0]["escalation_rate"] == 0.0


def test_api_stats_by_repo_rejects_invalid_range():
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/stats/by_repo?range=zzz")
    assert res.status_code == 400
    reader.stats_by_dimension.assert_not_awaited()


def test_api_stats_operations_passes_aggregate_through():
    """Route fetches raw rows from the reader and shapes them with the
    pure aggregator — verify the wiring."""
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.stats_operations.return_value = {
        "range": "24h",
        "rows": [
            {
                "token_usage": {"by_model": {
                    "claude-opus-4-7": {
                        "calls": 1, "input_tokens": 100_000, "output_tokens": 10_000,
                        "cache_read_tokens": 0, "cache_creation_tokens": 0,
                    },
                }},
                "duration_ms": 5000,
                "workflow": "pr_review",
            },
        ],
    }

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/stats/operations?range=24h")
    assert res.status_code == 200
    body = res.json()
    assert body["range"] == "24h"
    assert body["rows_considered"] == 1
    assert body["totals"]["input_tokens"] == 100_000
    assert body["cost_usd"] > 0
    assert body["duration_ms_p50"] == 5000


def test_api_stats_operations_rejects_invalid_range():
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/stats/operations?range=zzz")
    assert res.status_code == 400
    reader.stats_operations.assert_not_awaited()


def test_api_stats_operations_503_when_no_db():
    from fastapi.testclient import TestClient

    app = _make_app(trace_reader=None)
    client = TestClient(app)
    res = client.get("/api/stats/operations?range=24h")
    assert res.status_code == 503


def test_api_stats_confidence_returns_bins():
    """Histogram endpoint serializes 10 bins with label + count."""
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    reader.stats_confidence.return_value = {
        "range": "24h",
        "total": 5,
        "bins": [
            {"lo": round(i * 0.1, 1), "hi": round((i + 1) * 0.1, 1), "count": (1 if i in (4, 5, 6, 7, 8) else 0)}
            for i in range(10)
        ],
    }

    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/stats/confidence?range=24h")
    assert res.status_code == 200
    body = res.json()
    assert len(body["bins"]) == 10
    assert body["bins"][4]["count"] == 1
    assert body["total"] == 5
    reader.stats_confidence.assert_awaited_once_with("24h")


def test_api_stats_confidence_rejects_invalid_range():
    from fastapi.testclient import TestClient

    reader = AsyncMock()
    app = _make_app(trace_reader=reader)
    client = TestClient(app)
    res = client.get("/api/stats/confidence?range=nope")
    assert res.status_code == 400
    reader.stats_confidence.assert_not_awaited()


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
