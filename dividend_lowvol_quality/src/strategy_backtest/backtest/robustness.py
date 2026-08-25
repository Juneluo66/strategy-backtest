"""Repeatable parameter sweeps for post-data-coverage strategy checks."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import pandas as pd

from strategy_backtest.backtest.engine import backtest_monthly
from strategy_backtest.config import StrategyConfig


def run_top_n_sensitivity(
    snapshots: dict, prices: pd.DataFrame, config: StrategyConfig, top_ns: tuple[int, ...] = (20, 25, 30)
) -> pd.DataFrame:
    """Compare holdings-count variants on identical PIT input dates."""
    rows = []
    for top_n in top_ns:
        result = backtest_monthly(snapshots, prices, replace(config, top_n=top_n))
        rows.append({"variant": f"top_n={top_n}", **result["metrics"], "periods": len(result["periods"])})
    return pd.DataFrame(rows)


def strict_b_oat_specs(config: StrategyConfig) -> list[dict[str, Any]]:
    """Return serial one-at-a-time strict-B experiments around locked defaults.

    The caller is responsible for supplying matching snapshot partitions for
    volatility-window and rebalance-position changes.  This avoids falsely
    treating a 120-day feature panel as a 60/250-day experiment.
    """
    base = {
        "name": "base",
        "top_n": config.top_n,
        "volatility_window": config.volatility_window,
        "rebalance_position": config.rebalance_position,
        "high_dividend_percentile": config.high_dividend_percentile,
        "weighting": config.weighting,
        "max_industry_weight": config.max_industry_weight,
    }
    specs = [base]
    dimensions = {
        "volatility_window": (60, 250),
        "top_n": (20, 30, 50),
        "rebalance_position": ("middle", "last"),
        "high_dividend_percentile": (0.10, 0.30),
        "weighting": ("inverse_volatility",),
        "max_industry_weight": (0.15, 0.25),
    }
    for field, values in dimensions.items():
        for value in values:
            spec = dict(base)
            spec[field] = value
            spec["name"] = f"{field}={value}"
            specs.append(spec)
    return specs
