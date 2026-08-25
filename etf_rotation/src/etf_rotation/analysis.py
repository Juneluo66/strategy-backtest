"""Predeclared ablations and honest multiple-testing availability reports."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from etf_rotation.backtest import vector_backtest
from etf_rotation.config import RotationConfig

ABLATIONS = {
    "A0": {"factor_set": "momentum", "frequency": 1, "use_hysteresis": False, "use_regime_gate": False},
    "A1": {"factor_set": "composite_1", "frequency": 1, "use_hysteresis": False, "use_regime_gate": False},
    "A2": {"factor_set": "composite_1", "frequency": 5, "use_hysteresis": False, "use_regime_gate": False},
    "A3": {"factor_set": "composite_1", "frequency": 5, "use_hysteresis": True, "min_hold_days": 0, "max_replacements": 99, "use_regime_gate": False},
    "A4": {"factor_set": "composite_1", "frequency": 5, "use_hysteresis": True, "min_hold_days": 9, "max_replacements": 99, "use_regime_gate": False},
    "A5": {"factor_set": "composite_1", "frequency": 5, "use_hysteresis": True, "min_hold_days": 9, "max_replacements": 1, "use_regime_gate": False},
    "A6": {"factor_set": "composite_1", "frequency": 5, "use_hysteresis": True, "min_hold_days": 9, "max_replacements": 1, "use_regime_gate": True},
    "A7": {"factor_set": "composite_1", "frequency": 5, "use_hysteresis": True, "use_regime_gate": True},
    "A8": {"factor_set": "composite_1", "frequency": 5, "use_hysteresis": True, "use_regime_gate": True},
    "A9": {"factor_set": "composite_1", "frequency": 5, "use_hysteresis": True, "use_regime_gate": True},
    "A10": {"factor_set": "composite_1", "frequency": 5, "position_size": 3, "use_hysteresis": True, "use_regime_gate": True},
}


def ablation_table(scores_by_factor: dict[str, pd.DataFrame], prices: dict[str, pd.DataFrame],
                   config: RotationConfig) -> pd.DataFrame:
    """Run fixed ablations only; no result drives a parameter choice."""
    rows = []
    for name, changes in ABLATIONS.items():
        # A7 is explicitly a partial-factor exclusion when no external fields exist:
        # `scores` already labels partial availability, so the same observable OHLCV
        # set is retained while the report makes the equivalence explicit.
        scores = scores_by_factor[changes["factor_set"]]
        result = vector_backtest(scores, prices, replace(config, **changes))
        equity = result["equity"]
        monthly = equity.set_index("date")["return"].resample("ME").apply(lambda values: (1 + values).prod() - 1)
        trailing = {
            f"worst_{days}d": float(equity["return"].rolling(days).apply(lambda values: (1 + values).prod() - 1).min())
            for days in (5, 10, 20)
        }
        rows.append({
            "ablation": name, **result["metrics"], "turnover": float(equity["turnover"].sum()),
            "trade_count": len(result["trades"]), "total_fees": float(equity["turnover"].sum() * config.commission_a_share),
            "total_slippage": np.nan, "worst_month": float(monthly.min()) if not monthly.empty else np.nan,
            **trailing,
            "partial_factor_set": bool(scores["is_partial_factor_set"].any()),
        })
    return pd.DataFrame(rows)


def multiple_testing_report() -> tuple[pd.DataFrame, str]:
    """There is no local factor-search result; state that rather than inventing one."""
    table = pd.DataFrame([{
        "analysis": "candidate_distribution",
        "status": "not_available",
        "reason": "This independent project intentionally does not run the source project's 12,597-combination search.",
    }, {
        "analysis": "deflated_sharpe_ratio",
        "status": "not_available",
        "reason": "Requires a complete candidate return matrix and search-trial specification.",
    }, {
        "analysis": "PBO / White Reality Check / SPA",
        "status": "not_available",
        "reason": "Requires all candidate returns; do not estimate from a single frozen strategy.",
    }])
    markdown = "# Multiple-testing and selection risk\n\n" + table.to_markdown(index=False) + (
        "\n\nThe source's 12,597-combination selection is a material external validity risk. "
        "No local search is performed, so no candidate distribution, rank correlation, or factor frequency is fabricated."
    )
    return table, markdown
