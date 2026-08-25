"""Performance and relative metrics."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _cagr(nav: pd.Series) -> float:
    if len(nav) < 2:
        return float("nan")
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    if years <= 0:
        return float("nan")
    return float(nav.iloc[-1] ** (1.0 / years) - 1.0)


def _max_dd(nav: pd.Series) -> float:
    peak = nav.cummax()
    dd = nav / peak - 1.0
    return float(dd.min()) if len(dd) else float("nan")


def summary_stats(returns: pd.Series, *, rf_daily: pd.Series | None = None) -> dict:
    r = returns.dropna().astype(float)
    if len(r) < 2:
        return {}
    nav = (1.0 + r).cumprod()
    nav = nav / float(nav.iloc[0])
    ann = 252.0
    mu = float(r.mean() * ann)
    vol = float(r.std(ddof=1) * np.sqrt(ann))
    downside = r.clip(upper=0.0)
    dvol = float(downside.std(ddof=1) * np.sqrt(ann)) if downside.any() else float("nan")
    if rf_daily is not None:
        excess = r - rf_daily.reindex(r.index).fillna(0.0)
    else:
        excess = r
    sharpe = float(excess.mean() / excess.std(ddof=1) * np.sqrt(ann)) if excess.std(ddof=1) > 0 else float("nan")
    sortino = float(excess.mean() / (downside.std(ddof=1) + 1e-16) * np.sqrt(ann)) if downside.std(ddof=1) > 0 else float("nan")
    # Calmar
    mdd = _max_dd(nav)
    cagr = _cagr(nav)
    calmar = float(cagr / abs(mdd)) if mdd < 0 else float("nan")
    return {
        "start": str(r.index[0].date()),
        "end": str(r.index[-1].date()),
        "n_days": int(len(r)),
        "cagr": cagr,
        "ann_return_arith": mu,
        "ann_vol": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "max_drawdown": mdd,
        "final_nav": float(nav.iloc[-1]),
        "skew": float(r.skew()),
        "kurtosis": float(r.kurtosis()),
    }


def relative_to(strategy: pd.Series, benchmark: pd.Series) -> dict:
    aligned = pd.concat([strategy.rename("s"), benchmark.rename("b")], axis=1).dropna()
    if len(aligned) < 2:
        return {}
    nav_s = (1.0 + aligned["s"]).cumprod()
    nav_b = (1.0 + aligned["b"]).cumprod()
    nav_s = nav_s / float(nav_s.iloc[0])
    nav_b = nav_b / float(nav_b.iloc[0])
    rel = nav_s / nav_b
    active = aligned["s"] - aligned["b"]
    te = float(active.std(ddof=1) * np.sqrt(252))
    ir = float(active.mean() / active.std(ddof=1) * np.sqrt(252)) if active.std(ddof=1) > 0 else float("nan")
    years = (aligned.index[-1] - aligned.index[0]).days / 365.25
    rel_cagr = float(rel.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else float("nan")
    return {
        "final_relative_nav": float(rel.iloc[-1]),
        "relative_cagr": rel_cagr,
        "relative_max_dd": _max_dd(rel),
        "information_ratio": ir,
        "tracking_error": te,
        "active_ann_mean": float(active.mean() * 252),
    }


def occupancy(position: pd.Series, risk_on: str, risk_off: str) -> dict:
    p = position.dropna()
    n = len(p)
    if n == 0:
        return {}
    return {
        "pct_qqq": float((p == risk_on).mean()),
        "pct_shy": float((p == risk_off).mean()),
        "n_sessions": int(n),
    }
