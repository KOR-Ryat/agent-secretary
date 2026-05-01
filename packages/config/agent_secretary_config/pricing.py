"""Anthropic model unit prices for cost estimation.

Numbers are USD per 1M tokens. Update these when Anthropic changes
public pricing — the dashboard's cost card multiplies them against
the per-model token totals captured in pr_trace.token_usage.

Cache reads are charged at 10% of base input; cache creation carries
a 25% premium. We follow Anthropic's published cache pricing model.

If a model id appears in token_usage but isn't in MODEL_PRICES, the
aggregator treats its cost contribution as 0 (so a typo'd model id
doesn't crash the dashboard) and reports the unknown ids in the
response so the operator can update this table.
"""

from __future__ import annotations

from typing import Final, TypedDict


class ModelPrice(TypedDict):
    input_per_mtok: float
    output_per_mtok: float


# Per-million-token USD prices.
MODEL_PRICES: Final[dict[str, ModelPrice]] = {
    "claude-opus-4-7": {"input_per_mtok": 15.0, "output_per_mtok": 75.0},
    "claude-opus-4-6": {"input_per_mtok": 15.0, "output_per_mtok": 75.0},
    "claude-sonnet-4-6": {"input_per_mtok": 3.0, "output_per_mtok": 15.0},
    "claude-haiku-4-5": {"input_per_mtok": 1.0, "output_per_mtok": 5.0},
    "claude-haiku-4-5-20251001": {"input_per_mtok": 1.0, "output_per_mtok": 5.0},
}

CACHE_READ_DISCOUNT: Final[float] = 0.10   # cache reads charged at 10% of input rate
CACHE_WRITE_PREMIUM: Final[float] = 1.25   # cache creation charged at 125% of input rate


def cost_usd(model: str, *, input_tokens: int, output_tokens: int,
             cache_read_tokens: int = 0, cache_creation_tokens: int = 0) -> float:
    """USD cost for a (model, token-counts) combination.

    Returns 0.0 if ``model`` isn't in ``MODEL_PRICES`` so the dashboard
    aggregator stays robust to typos / new model ids."""
    price = MODEL_PRICES.get(model)
    if price is None:
        return 0.0
    in_rate = price["input_per_mtok"] / 1_000_000
    out_rate = price["output_per_mtok"] / 1_000_000
    return (
        input_tokens * in_rate
        + output_tokens * out_rate
        + cache_read_tokens * in_rate * CACHE_READ_DISCOUNT
        + cache_creation_tokens * in_rate * CACHE_WRITE_PREMIUM
    )
