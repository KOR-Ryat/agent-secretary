"""Operations stats aggregation: token totals, cost, and latency.

Pure functions (no DB / Redis here) so they're easy to unit-test —
the route layer fetches raw rows from TraceReader, then funnels them
through ``aggregate_operations`` for shaping.
"""

from __future__ import annotations

from typing import Any

from agent_secretary_config import MODEL_PRICES, cost_usd


def _zero_model_totals() -> dict[str, int]:
    return {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
    }


def _percentile(sorted_values: list[int], p: float) -> int | None:
    """Linear-interpolation percentile. Returns None on empty input."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    # p in [0,1]
    idx = p * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return round(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac)


def aggregate_operations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up per-row token_usage + duration_ms into:

      - by_model: per-model totals
      - totals: grand totals (calls/input/output/cache)
      - cost_usd: estimated cost (using MODEL_PRICES at call time —
        traces store raw tokens so historic cost can be recomputed if
        prices change)
      - duration_ms_avg / p50 / p95
      - unknown_models: model ids seen in token_usage but not in
        MODEL_PRICES (operator should update the price table)
    """
    by_model: dict[str, dict[str, int]] = {}
    durations: list[int] = []
    workflows: dict[str, int] = {}

    for r in rows:
        usage = r.get("token_usage")
        per_model = (usage or {}).get("by_model") or {}
        for model, t in per_model.items():
            slot = by_model.setdefault(model, _zero_model_totals())
            slot["calls"] += int(t.get("calls", 0))
            slot["input_tokens"] += int(t.get("input_tokens", 0))
            slot["output_tokens"] += int(t.get("output_tokens", 0))
            slot["cache_read_tokens"] += int(t.get("cache_read_tokens", 0))
            slot["cache_creation_tokens"] += int(t.get("cache_creation_tokens", 0))
        d = r.get("duration_ms")
        if d is not None:
            durations.append(int(d))
        wf = r.get("workflow")
        if wf:
            workflows[wf] = workflows.get(wf, 0) + 1

    totals = _zero_model_totals()
    cost = 0.0
    unknown_models: list[str] = []
    cost_by_model: dict[str, float] = {}
    for model, t in by_model.items():
        for k in totals:
            totals[k] += t[k]
        c = cost_usd(
            model,
            input_tokens=t["input_tokens"],
            output_tokens=t["output_tokens"],
            cache_read_tokens=t["cache_read_tokens"],
            cache_creation_tokens=t["cache_creation_tokens"],
        )
        cost_by_model[model] = c
        cost += c
        if model not in MODEL_PRICES:
            unknown_models.append(model)

    durations.sort()
    return {
        "rows_considered": len(rows),
        "by_model": by_model,
        "totals": totals,
        "cost_usd": round(cost, 4),
        "cost_by_model": {m: round(v, 4) for m, v in cost_by_model.items()},
        "duration_ms_avg": int(sum(durations) / len(durations)) if durations else None,
        "duration_ms_p50": _percentile(durations, 0.5),
        "duration_ms_p95": _percentile(durations, 0.95),
        "duration_samples": len(durations),
        "workflows": workflows,
        "unknown_models": sorted(unknown_models),
    }
