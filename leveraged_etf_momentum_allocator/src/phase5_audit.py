"""Phase 5 helpers: crisis-robust score, walk-forward, crisis behavior, exposure scale."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from metrics import cagr, calmar, compute_metrics, max_drawdown, sharpe
from overfitting_audit import (
    CRISIS_PERIODS,
    leave_one_crisis_out,
    random_neighborhood_distribution,
    rolling_stability,
    rolling_summary,
)


def scale_equity_exposure(equity: pd.DataFrame, exposure: float) -> pd.DataFrame:
    """Research-only portfolio exposure scaling (cash earns 0). Does not change signals."""
    eq = equity.copy()
    for col in ("gross_return", "net_return"):
        if col in eq.columns:
            eq[col] = eq[col] * float(exposure)
    eq["equity_gross"] = (1 + eq["gross_return"]).cumprod()
    eq["equity_net"] = (1 + eq["net_return"]).cumprod()
    eq["exposure_scale"] = float(exposure)
    return eq


def crisis_robust_score(row: dict[str, Any]) -> float:
    """Composite score — prefers stability over raw CAGR. Not a formal statistic.

    Higher is better. Components are clipped/normalized heuristically.
    """
    full = float(row.get("cagr", 0) or 0)
    ex_c = float(row.get("ex_covid_cagr", 0) or 0)
    ex_2 = float(row.get("ex_2022_cagr", 0) or 0)
    ex_b = float(row.get("ex_both_cagr", 0) or 0)
    med = float(row.get("rand_median_cagr", full) or full)
    p10 = float(row.get("rand_p10_cagr", full) or full)
    pct = float(row.get("rand_percentile", 50) or 50)
    w3 = float(row.get("roll3_win_tqqq", 0) or 0)
    w5 = float(row.get("roll5_win_tqqq", 0) or 0)
    sh = float(row.get("sharpe", 0) or 0)
    dd = abs(float(row.get("max_dd", -1) or -1))
    turn = float(row.get("annual_turnover", 50) or 50)
    n_param = float(row.get("n_params_total", 12) or 12)
    n_br = float(row.get("n_branches", 14) or 14)

    # Soft caps so extreme CAGR does not dominate
    def soft(x: float, cap: float = 1.5) -> float:
        return min(max(x, 0.0), cap)

    score = (
        0.12 * soft(full)
        + 0.18 * soft(ex_c)
        + 0.12 * soft(ex_2)
        + 0.18 * soft(ex_b)
        + 0.12 * soft(med)
        + 0.08 * soft(p10)
        + 0.08 * w5
        + 0.05 * w3
        + 0.08 * min(sh / 2.0, 1.5)
        - 0.06 * min(dd, 1.0)
        - 0.03 * min(turn / 100.0, 2.0)
        - 0.04 * (n_param / 20.0)
        - 0.04 * (n_br / 14.0)
        - 0.10 * max(0.0, (pct - 85) / 15.0)  # penalize extreme top-tail params
    )
    return float(score)


def crisis_behavior_profile(
    signal_log: pd.DataFrame,
    crisis_periods: list[tuple[str, str, str]] = CRISIS_PERIODS,
) -> pd.DataFrame:
    """Directional behavior per crisis — not return-focused."""
    if signal_log.empty:
        return pd.DataFrame()
    log = signal_log.copy()
    log["date"] = pd.to_datetime(log["date"])
    rows = []
    risk_off = {"BSV", "CASH"}
    shortish = {"TECS", "SQQQ", "UVXY"}
    rebound_long = {"TECL", "SPXL", "TQQQ"}
    for name, start, end in crisis_periods:
        mask = (log["date"] >= pd.Timestamp(start)) & (log["date"] <= pd.Timestamp(end))
        sub = log.loc[mask]
        if sub.empty:
            rows.append({"crisis": name, "days": 0, "note": "no overlap"})
            continue
        targets = sub["target"].value_counts(normalize=True)
        regimes = sub["market_regime"].value_counts(normalize=True) if "market_regime" in sub else {}
        rows.append(
            {
                "crisis": name,
                "days": len(sub),
                "pct_bear_regime": float(regimes.get("BEAR", 0.0)) if hasattr(regimes, "get") else float((sub["market_regime"] == "BEAR").mean()),
                "pct_risk_off": float(sub["target"].isin(risk_off).mean()),
                "pct_shortish": float(sub["target"].isin(shortish).mean()),
                "pct_rebound_long": float(sub["target"].isin(rebound_long).mean()),
                "top_target": str(targets.index[0]) if len(targets) else "NA",
                "top_target_pct": float(targets.iloc[0]) if len(targets) else 0.0,
                "unique_targets": int(sub["target"].nunique()),
            }
        )
    return pd.DataFrame(rows)


def loo_named(equity: pd.DataFrame, closes: pd.DataFrame) -> dict[str, float]:
    loo = leave_one_crisis_out(equity, closes, CRISIS_PERIODS)
    out = {}
    for _, r in loo.iterrows():
        out[str(r["scenario"])] = float(r["cagr"])
    return out


def active_branch_count(signal_log: pd.DataFrame) -> int:
    if signal_log.empty or "branch_id" not in signal_log.columns:
        return 0
    ids = signal_log["branch_id"].dropna().astype(str)
    ids = ids[~ids.str.endswith("_PRUNED")]
    return int(ids.nunique())


def prune_candidates_from_attribution(branch_df: pd.DataFrame) -> list[dict]:
    """Mark PRUNE_CANDIDATE branches: rare + low incremental, or crisis-narrow."""
    if branch_df.empty:
        return []
    ranked = branch_df.sort_values("time_pct")
    cands = []
    for _, r in ranked.iterrows():
        bid = r["branch_id"]
        if bid == "B3":
            continue  # never prune core bull TQQQ
        time_pct = float(r["time_pct"])
        inc = float(r.get("incremental_vs_tqqq", 0) or 0)
        rare_low = time_pct < 0.01 and abs(inc) < 2.0
        rare_neg = time_pct < 0.015 and inc < 0
        if rare_low or rare_neg or time_pct < 0.005:
            cands.append(
                {
                    "branch_id": bid,
                    "time_pct": time_pct,
                    "incremental_vs_tqqq": inc,
                    "reason": "rare_low" if rare_low else ("rare_neg" if rare_neg else "ultra_rare"),
                    "mark": "PRUNE_CANDIDATE",
                }
            )
    return cands
