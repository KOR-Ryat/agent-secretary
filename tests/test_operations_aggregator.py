"""Tests for the operations stats aggregator.

The aggregator turns raw `pr_trace` rows (with token_usage JSONB and
duration_ms columns) into the rolled-up shape the dashboard renders.
We exercise it directly so the dashboard can rely on its contract
without spinning up Postgres.
"""

from __future__ import annotations


def _row(by_model: dict, duration_ms: int | None = 1000, workflow: str = "pr_review"):
    return {
        "token_usage": {"by_model": by_model},
        "duration_ms": duration_ms,
        "workflow": workflow,
    }


def test_empty_rows_yields_zero_aggregate():
    from ingress.dashboard.operations import aggregate_operations

    agg = aggregate_operations([])
    assert agg["rows_considered"] == 0
    assert agg["totals"]["calls"] == 0
    assert agg["cost_usd"] == 0.0
    assert agg["duration_ms_p50"] is None
    assert agg["unknown_models"] == []


def test_single_row_opus_cost():
    """1M input + 100k output on opus → 15 + 7.5 = $22.50."""
    from ingress.dashboard.operations import aggregate_operations

    rows = [
        _row({"claude-opus-4-7": {
            "calls": 1, "input_tokens": 1_000_000, "output_tokens": 100_000,
            "cache_read_tokens": 0, "cache_creation_tokens": 0,
        }}),
    ]
    agg = aggregate_operations(rows)
    assert agg["cost_usd"] == 22.5
    assert agg["totals"]["input_tokens"] == 1_000_000
    assert agg["by_model"]["claude-opus-4-7"]["calls"] == 1


def test_multi_model_aggregation():
    """Costs sum across models — opus + sonnet should each contribute."""
    from ingress.dashboard.operations import aggregate_operations

    rows = [
        _row({
            "claude-opus-4-7":   {"calls": 1, "input_tokens": 100_000, "output_tokens": 10_000,
                                  "cache_read_tokens": 0, "cache_creation_tokens": 0},
            "claude-sonnet-4-6": {"calls": 5, "input_tokens": 500_000, "output_tokens": 50_000,
                                  "cache_read_tokens": 0, "cache_creation_tokens": 0},
        }),
    ]
    agg = aggregate_operations(rows)
    # opus: 100k * $15/M + 10k * $75/M = $1.50 + $0.75 = $2.25
    # sonnet: 500k * $3/M + 50k * $15/M = $1.50 + $0.75 = $2.25
    assert agg["cost_usd"] == 4.5
    assert agg["by_model"]["claude-opus-4-7"]["calls"] == 1
    assert agg["by_model"]["claude-sonnet-4-6"]["calls"] == 5


def test_unknown_model_does_not_crash_and_is_reported():
    """Operator-side typos / new model ids → cost contribution 0 + flagged."""
    from ingress.dashboard.operations import aggregate_operations

    rows = [
        _row({"claude-bogus-9": {
            "calls": 1, "input_tokens": 1_000_000, "output_tokens": 0,
            "cache_read_tokens": 0, "cache_creation_tokens": 0,
        }}),
    ]
    agg = aggregate_operations(rows)
    assert agg["cost_usd"] == 0.0
    assert "claude-bogus-9" in agg["unknown_models"]


def test_duration_percentiles():
    """p50 should be the middle, p95 near the top."""
    from ingress.dashboard.operations import aggregate_operations

    rows = [_row({}, duration_ms=d) for d in [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]]
    agg = aggregate_operations(rows)
    # 10 samples, p50 = avg of indices [4,5] (500, 600) = 550
    assert agg["duration_ms_p50"] == 550
    # p95 near sample 9.05 → between 900 and 1000
    assert 900 <= agg["duration_ms_p95"] <= 1000
    assert agg["duration_ms_avg"] == 550


def test_duration_skips_null():
    """Rows that haven't completed (no duration_ms) are skipped, not 0."""
    from ingress.dashboard.operations import aggregate_operations

    rows = [
        _row({}, duration_ms=None),
        _row({}, duration_ms=200),
        _row({}, duration_ms=400),
    ]
    agg = aggregate_operations(rows)
    assert agg["duration_samples"] == 2
    assert agg["duration_ms_avg"] == 300


def test_workflow_counts():
    from ingress.dashboard.operations import aggregate_operations

    rows = [
        _row({}, workflow="pr_review"),
        _row({}, workflow="pr_review"),
        _row({}, workflow="code_analyze"),
    ]
    agg = aggregate_operations(rows)
    assert agg["workflows"] == {"pr_review": 2, "code_analyze": 1}


def test_cache_token_costs():
    """Cache reads at 10% of input, cache writes at 125% of input."""
    from agent_secretary_config import cost_usd

    # Sonnet: input rate = $3/M.
    # 1M cache read = 1M * $3/M * 0.10 = $0.30
    # 1M cache create = 1M * $3/M * 1.25 = $3.75
    c = cost_usd(
        "claude-sonnet-4-6",
        input_tokens=0, output_tokens=0,
        cache_read_tokens=1_000_000, cache_creation_tokens=0,
    )
    assert abs(c - 0.30) < 1e-9

    c2 = cost_usd(
        "claude-sonnet-4-6",
        input_tokens=0, output_tokens=0,
        cache_read_tokens=0, cache_creation_tokens=1_000_000,
    )
    assert abs(c2 - 3.75) < 1e-9
