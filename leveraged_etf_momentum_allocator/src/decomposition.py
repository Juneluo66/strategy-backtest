"""Return decomposition — timing, selection, leverage components."""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd


def decompose_returns(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    static_returns: Optional[pd.Series] = None,
    unleveraged_returns: Optional[pd.Series] = None,
) -> dict[str, Any]:
    """Simple linear decomposition — not claiming perfect attribution."""
    aligned = pd.concat(
        [strategy_returns.rename("strategy"), benchmark_returns.rename("benchmark")],
        axis=1,
    ).dropna()
    if aligned.empty:
        return {"error": "insufficient overlap"}

    cov = aligned["strategy"].cov(aligned["benchmark"])
    var = aligned["benchmark"].var()
    beta = cov / var if var > 0 else float("nan")
    beta_component = beta * aligned["benchmark"]
    residual = aligned["strategy"] - beta_component

    result: dict[str, Any] = {
        "beta": float(beta),
        "beta_component_cagr": float((1 + beta_component).prod() ** (252 / len(beta_component)) - 1),
        "residual_cagr": float((1 + residual).prod() ** (252 / len(residual)) - 1),
        "strategy_cagr": float((1 + aligned["strategy"]).prod() ** (252 / len(aligned)) - 1),
        "benchmark_cagr": float((1 + aligned["benchmark"]).prod() ** (252 / len(aligned)) - 1),
    }

    if static_returns is not None:
        static_aligned = static_returns.reindex(aligned.index).dropna()
        if not static_aligned.empty:
            result["static_allocation_cagr"] = float(
                (1 + static_aligned).prod() ** (252 / len(static_aligned)) - 1
            )
            result["timing_contribution"] = result["strategy_cagr"] - result["static_allocation_cagr"]

    if unleveraged_returns is not None:
        unlev = unleveraged_returns.reindex(aligned.index).dropna()
        if not unlev.empty:
            result["unleveraged_cagr"] = float((1 + unlev).prod() ** (252 / len(unlev)) - 1)
            result["leverage_contribution"] = result["strategy_cagr"] - result["unleveraged_cagr"]
            result["selection_contribution"] = result["unleveraged_cagr"] - result.get(
                "benchmark_cagr", float("nan")
            )

    return result
