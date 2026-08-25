from __future__ import annotations

import numpy as np
import pandas as pd


def summary_stats(returns: pd.Series) -> dict:
    r = returns.dropna().astype(float)
    if len(r) < 2:
        return {}
    nav = (1.0 + r).cumprod()
    nav = nav / float(nav.iloc[0])
    ann = 252.0
    vol = float(r.std(ddof=1) * np.sqrt(ann))
    sharpe = float(r.mean() / r.std(ddof=1) * np.sqrt(ann)) if r.std(ddof=1) > 0 else float("nan")
    years = (r.index[-1] - r.index[0]).days / 365.25
    cagr = float(nav.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else float("nan")
    peak = nav.cummax()
    mdd = float((nav / peak - 1.0).min())
    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "ann_vol": vol,
        "max_dd": mdd,
        "final_nav": float(nav.iloc[-1]),
        "n_days": int(len(r)),
    }


def ann_vol(r: pd.Series) -> float:
    x = r.dropna()
    return float(x.std(ddof=1) * np.sqrt(252)) if len(x) > 5 else float("nan")


def vol_matched_weight(strat: pd.Series, on_r: pd.Series, off_r: pd.Series) -> float:
    target = ann_vol(strat)
    grid = np.linspace(0, 1, 101)
    vols = np.array([ann_vol(ww * on_r + (1 - ww) * off_r) for ww in grid])
    return float(grid[int(np.argmin(np.abs(vols - target)))])
