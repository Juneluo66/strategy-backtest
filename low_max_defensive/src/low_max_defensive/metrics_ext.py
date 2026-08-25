"""Extended performance metrics for defensive equity research."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def _finite(series: pd.Series) -> pd.Series:
    return series.replace([np.inf, -np.inf], np.nan).dropna()


def max_drawdown(returns: pd.Series) -> float:
    equity = (1 + _finite(returns)).cumprod()
    if equity.empty:
        return float("nan")
    return float((equity / equity.cummax() - 1).min())


def cagr(returns: pd.Series) -> float:
    r = _finite(returns)
    if r.empty:
        return float("nan")
    years = len(r) / 252
    if years <= 0:
        return float("nan")
    return float((1 + r).prod() ** (1 / years) - 1)


def ann_vol(returns: pd.Series) -> float:
    r = _finite(returns)
    if len(r) < 2:
        return float("nan")
    return float(r.std(ddof=1) * np.sqrt(252))


def sharpe(returns: pd.Series) -> float:
    r = _finite(returns)
    if len(r) < 2 or r.std(ddof=1) == 0:
        return float("nan")
    return float(r.mean() / r.std(ddof=1) * np.sqrt(252))


def sortino(returns: pd.Series) -> float:
    r = _finite(returns)
    downside = r[r < 0]
    if len(r) < 2 or downside.empty or downside.std(ddof=1) == 0:
        return float("nan")
    return float(r.mean() / downside.std(ddof=1) * np.sqrt(252))


def calmar(returns: pd.Series) -> float:
    dd = max_drawdown(returns)
    if not np.isfinite(dd) or dd == 0:
        return float("nan")
    return float(cagr(returns) / abs(dd))


def beta_to(returns: pd.Series, benchmark: pd.Series) -> float:
    aligned = pd.concat([returns.rename("y"), benchmark.rename("x")], axis=1).dropna()
    if len(aligned) < 60 or aligned["x"].var() == 0:
        return float("nan")
    return float(aligned["y"].cov(aligned["x"]) / aligned["x"].var())


def downside_beta(returns: pd.Series, benchmark: pd.Series) -> float:
    aligned = pd.concat([returns.rename("y"), benchmark.rename("x")], axis=1).dropna()
    down = aligned[aligned["x"] < 0]
    if len(down) < 40 or down["x"].var() == 0:
        return float("nan")
    return float(down["y"].cov(down["x"]) / down["x"].var())


def worst_month(returns: pd.Series) -> float:
    monthly = _finite(returns).resample("ME").apply(lambda x: (1 + x).prod() - 1)
    return float(monthly.min()) if not monthly.empty else float("nan")


def capture_ratio(returns: pd.Series, benchmark: pd.Series, upside: bool) -> float:
    aligned = pd.concat([returns.rename("y"), benchmark.rename("x")], axis=1).dropna()
    mask = aligned["x"] > 0 if upside else aligned["x"] < 0
    subset = aligned.loc[mask]
    if subset.empty or subset["x"].mean() == 0:
        return float("nan")
    return float(subset["y"].mean() / subset["x"].mean())


def tracking_error(excess: pd.Series) -> float:
    r = _finite(excess)
    if len(r) < 2:
        return float("nan")
    return float(r.std(ddof=1) * np.sqrt(252))


def information_ratio(excess: pd.Series) -> float:
    r = _finite(excess)
    if len(r) < 2 or r.std(ddof=1) == 0:
        return float("nan")
    return float(r.mean() / r.std(ddof=1) * np.sqrt(252))


def turnover_stats(trades: pd.DataFrame) -> dict[str, float]:
    if trades is None or trades.empty:
        return {"one_way_turnover": 0.0, "annualized_turnover": 0.0, "cost_total": 0.0}
    daily = trades.groupby("date")["turnover"].sum()
    span_years = max(
        (pd.to_datetime(daily.index).max() - pd.to_datetime(daily.index).min()).days / 365.25,
        1 / 12,
    )
    return {
        "one_way_turnover": float(daily.sum() / 2),
        "annualized_turnover": float(daily.sum() / 2 / span_years),
        "cost_total": float(trades["cost"].sum()) if "cost" in trades else 0.0,
    }


def portfolio_report(
    results: pd.DataFrame,
    trades: pd.DataFrame,
    benchmark_returns: pd.Series,
    label: str,
    comparable_start: Optional[str] = None,
    comparable_end: Optional[str] = None,
) -> dict:
    frame = results
    if comparable_start is not None:
        frame = frame.loc[pd.Timestamp(comparable_start) : pd.Timestamp(comparable_end or frame.index.max())]
    trades_slice = trades
    if not trades.empty and comparable_start is not None:
        mask = (pd.to_datetime(trades["date"]) >= pd.Timestamp(comparable_start)) & (
            pd.to_datetime(trades["date"]) <= pd.Timestamp(comparable_end or frame.index.max())
        )
        trades_slice = trades.loc[mask]

    net = frame["net_return"]
    gross = frame["gross_return"]
    bench = benchmark_returns.reindex(net.index).dropna()
    aligned = pd.concat([net.rename("net"), bench.rename("bench")], axis=1).dropna()
    excess = aligned["net"] - aligned["bench"]
    turn = turnover_stats(trades_slice)
    gross_cagr = cagr(gross)
    net_cagr = cagr(net)
    return {
        "label": label,
        "start": str(frame.index.min().date()) if len(frame) else None,
        "end": str(frame.index.max().date()) if len(frame) else None,
        "n_days": int(len(frame)),
        "gross_cagr": gross_cagr,
        "net_cagr": net_cagr,
        "volatility": ann_vol(net),
        "gross_sharpe": sharpe(gross),
        "net_sharpe": sharpe(net),
        "sortino": sortino(net),
        "max_drawdown": max_drawdown(net),
        "calmar": calmar(net),
        "beta_spy": beta_to(aligned["net"], aligned["bench"]) if len(aligned) else float("nan"),
        "downside_beta": downside_beta(aligned["net"], aligned["bench"]) if len(aligned) else float("nan"),
        "worst_month": worst_month(net),
        "annualized_turnover": turn["annualized_turnover"],
        "cost_drag_cagr": (gross_cagr - net_cagr) if np.isfinite(gross_cagr) and np.isfinite(net_cagr) else float("nan"),
        "excess_cagr": cagr(excess) if len(aligned) else float("nan"),
        "tracking_error": tracking_error(excess) if len(aligned) else float("nan"),
        "information_ratio": information_ratio(excess) if len(aligned) else float("nan"),
        "upside_capture": capture_ratio(aligned["net"], aligned["bench"], True) if len(aligned) else float("nan"),
        "downside_capture": capture_ratio(aligned["net"], aligned["bench"], False) if len(aligned) else float("nan"),
    }
