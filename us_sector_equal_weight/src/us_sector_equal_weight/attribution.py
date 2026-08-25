"""Return-source decomposition for EW9 (no PIT cap-weight backfill)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .schedules import SECTORS


def average_weights(weights: pd.DataFrame, symbols: list[str] | None = None) -> pd.Series:
    symbols = list(symbols or SECTORS)
    if weights.empty:
        return pd.Series({s: np.nan for s in symbols})
    cols = [c for c in symbols if c in weights.columns]
    return weights[cols].mean()


def sector_return_contributions(
    weights: pd.DataFrame,
    closes: pd.DataFrame,
    symbols: list[str] | None = None,
) -> pd.DataFrame:
    """Approximate Brinson-style arithmetic contribution: w_{t-1} * r_t."""
    symbols = list(symbols or SECTORS)
    rets = closes[symbols].pct_change(fill_method=None)
    aligned = weights.reindex(rets.index).shift(1)
    contrib = aligned[symbols] * rets[symbols]
    total = contrib.sum(axis=0)
    share = total / total.replace(0, np.nan).sum()
    return pd.DataFrame(
        {
            "total_contribution": total,
            "share_of_contrib_mass": share,
            "avg_weight": aligned[symbols].mean(),
            "asset_cagr_proxy": (1 + rets[symbols]).prod() ** (252 / max(len(rets), 1)) - 1,
        }
    )


def rebalance_vs_hold_gap(ew_net: pd.Series, hold_net: pd.Series) -> dict:
    aligned = pd.concat([ew_net.rename("ew"), hold_net.rename("hold")], axis=1).dropna()
    if aligned.empty:
        return {"status": "EMPTY"}
    years = max((aligned.index.max() - aligned.index.min()).days / 365.25, 1 / 12)
    ew_nav = (1 + aligned["ew"]).cumprod()
    h_nav = (1 + aligned["hold"]).cumprod()
    return {
        "status": "OK",
        "ew_cagr": float(ew_nav.iloc[-1] ** (1 / years) - 1),
        "hold_cagr": float(h_nav.iloc[-1] ** (1 / years) - 1),
        "rebalance_cagr_edge": float(ew_nav.iloc[-1] ** (1 / years) - 1) - float(h_nav.iloc[-1] ** (1 / years) - 1),
        "final_rel_ew_over_hold": float(ew_nav.iloc[-1] / h_nav.iloc[-1]),
    }


def tech_weight_gap(avg_w: pd.Series, spy_tech_proxy: float | None = None) -> dict:
    """XLK average weight vs equal 1/9; SPY tech share NOT_COMPUTED without PIT."""
    return {
        "ew9_avg_xlk": float(avg_w.get("XLK", np.nan)),
        "ew9_target_xlk": 1.0 / 9.0,
        "spy_tech_weight_pit": "NOT_COMPUTED",
        "spy_tech_proxy_note": spy_tech_proxy,
        "sector_cap_weight_proxy": "NOT_COMPUTED_no_reliable_PIT_sector_weights",
    }


def single_sector_dominance(contrib: pd.DataFrame, threshold: float = 0.40) -> dict:
    if contrib.empty or contrib["share_of_contrib_mass"].isna().all():
        return {"dominated": False}
    top = contrib["share_of_contrib_mass"].abs().sort_values(ascending=False)
    name = top.index[0]
    share = float(top.iloc[0])
    return {
        "top_sector": name,
        "top_share": share,
        "dominated": bool(share >= threshold),
        "threshold": threshold,
    }
