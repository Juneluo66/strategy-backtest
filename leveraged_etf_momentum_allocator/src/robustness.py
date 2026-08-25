"""Threshold robustness and cost stress — post-replication only."""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from backtest import run_conditional_rotation
from config import ProjectConfig
from execution import ExecutionMode
from metrics import compute_metrics


THRESHOLD_PERTURBATIONS = {
    "qqq_rsi_overbought": [79, 80, 81, 82, 83],
    "spy_rsi_overbought": [78, 79, 80, 81, 82],
    "tqqq_rsi_oversold": [28, 29, 30, 31, 32],
    "spy_rsi_oversold": [28, 29, 30, 31, 32],
    "uvxy_high": [70, 72, 74, 76, 78],
    "uvxy_extreme": [80, 82, 84, 86, 88],
    "sqqq_rsi_branch_1": [29, 30, 31, 32, 33],
    "sqqq_rsi_branch_2": [32, 33, 34, 35, 36],
}


def run_threshold_robustness(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    cfg: ProjectConfig,
) -> pd.DataFrame:
    base = cfg.thresholds()
    rows: list[dict[str, Any]] = []
    # Original baseline
    res = run_conditional_rotation(opens, closes, cfg, mode=ExecutionMode.QC_DAILY_SEMANTICS)
    m = compute_metrics(res["equity"], res["trades"])
    rows.append({"parameter": "BASELINE", "value": "ORIGINAL", "tag": "ORIGINAL", ** _mrow(m, res)})

    for param, values in THRESHOLD_PERTURBATIONS.items():
        original_val = base[param]
        for v in values:
            if v == original_val:
                tag = "ORIGINAL"
            else:
                tag = "ROBUSTNESS_ONLY"
            thresh = dict(base)
            thresh[param] = v
            res = run_conditional_rotation(
                opens, closes, cfg, mode=ExecutionMode.QC_DAILY_SEMANTICS, thresholds=thresh
            )
            m = compute_metrics(res["equity"], res["trades"])
            rows.append({"parameter": param, "value": v, "tag": tag, **_mrow(m, res)})
    return pd.DataFrame(rows)


def _mrow(m: dict, res: dict) -> dict:
    return {
        "cagr": m["cagr_net"],
        "sharpe": m["sharpe_rf0"],
        "max_dd": m["max_drawdown"],
        "target_changes": res["target_change_count"],
    }


def run_cost_stress(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    cfg: ProjectConfig,
) -> pd.DataFrame:
    scenarios = [
        ("0bps", 0, 0),
        ("5bps", 0, 5),
        ("10bps", 0, 10),
        ("25bps", 0, 25),
        ("50bps", 0, 50),
    ]
    rows = []
    for name, comm, slip in scenarios:
        res = run_conditional_rotation(
            opens,
            closes,
            cfg,
            mode=ExecutionMode.QC_DAILY_SEMANTICS,
            commission_bps=comm,
            slippage_bps=slip,
        )
        m = compute_metrics(res["equity"], res["trades"])
        rows.append(
            {
                "scenario": name,
                "cagr_gross": m["cagr_gross"],
                "cagr_net": m["cagr_net"],
                "sharpe": m["sharpe_rf0"],
                "max_dd": m["max_drawdown"],
                "target_changes": res["target_change_count"],
                "trades": res["actual_trade_count"],
            }
        )
    return pd.DataFrame(rows)
