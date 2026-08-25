"""Performance, relative metrics, and factor regressions.

Formal relative wealth / underwater uses Metric C only:
  relative_nav = strategy_nav / benchmark_nav
  (both rebased to 1.0 on the strict common start date).

Arithmetic excess (r_s - r_b) is allowed only for mean/TE/IR/annual return
differences — never for relative NAV or relative underwater.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# Forbidden pattern for formal relative wealth (kept as documentation + tests).
FORBIDDEN_RELATIVE_WEALTH_FORMULA = "(1 + strategy_return - benchmark_return).cumprod()"
METRIC_C_DEFINITION = (
    "relative_nav_t = nav_strategy_t / nav_benchmark_t "
    "(both rebased to 1.0 at the first common date after strict intersection). "
    "Relative underwater = relative_nav / relative_nav.cummax() - 1."
)


def _stats(returns: pd.Series) -> dict[str, float]:
    returns = returns.dropna()
    if returns.empty:
        return {
            "cagr": np.nan,
            "volatility": np.nan,
            "sharpe": np.nan,
            "sortino": np.nan,
            "max_drawdown": np.nan,
            "calmar": np.nan,
            "worst_month": np.nan,
            "worst_year": np.nan,
            "month_win_rate": np.nan,
            "year_win_rate": np.nan,
        }
    equity = (1 + returns).cumprod()
    years = len(returns) / 252.0
    vol = float(returns.std(ddof=1) * np.sqrt(252)) if len(returns) > 1 else np.nan
    cagr = float(equity.iloc[-1] ** (1 / years) - 1) if years > 0 else np.nan
    downside = returns[returns < 0]
    sortino = (
        float(returns.mean() / downside.std(ddof=1) * np.sqrt(252))
        if len(downside) > 1 and downside.std(ddof=1)
        else np.nan
    )
    max_dd = float((equity / equity.cummax() - 1).min())
    monthly = returns.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    yearly = returns.resample("YE").apply(lambda x: (1 + x).prod() - 1)
    return {
        "cagr": cagr,
        "volatility": vol,
        "sharpe": float(returns.mean() / returns.std(ddof=1) * np.sqrt(252))
        if len(returns) > 1 and returns.std(ddof=1)
        else np.nan,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "calmar": (cagr / abs(max_dd)) if max_dd else np.nan,
        "worst_month": float(monthly.min()) if len(monthly) else np.nan,
        "worst_year": float(yearly.min()) if len(yearly) else np.nan,
        "month_win_rate": float((monthly > 0).mean()) if len(monthly) else np.nan,
        "year_win_rate": float((yearly > 0).mean()) if len(yearly) else np.nan,
    }


def underwater_stats(returns: pd.Series) -> dict[str, float]:
    """Absolute NAV underwater on a return series (NaNs dropped; not filled with 0)."""
    r = returns.dropna()
    if r.empty:
        return {"longest_underwater_days": np.nan, "current_drawdown": np.nan}
    equity = (1 + r).cumprod()
    dd = equity / equity.cummax() - 1
    under = dd < -1e-15
    longest = current = 0
    for flag in under:
        current = current + 1 if flag else 0
        longest = max(longest, current)
    return {
        "longest_underwater_days": float(longest),  # trading sessions
        "current_drawdown": float(dd.iloc[-1]),
    }


def _month_span(start: pd.Timestamp, end: pd.Timestamp) -> int:
    a = pd.Timestamp(start).to_period("M")
    b = pd.Timestamp(end).to_period("M")
    return int((b.year - a.year) * 12 + (b.month - a.month)) + 1


def _longest_under_streak(under_flags: pd.Series):
    longest = cur = 0
    best_start = best_end = None
    run_start = None
    for t, flag in under_flags.items():
        if bool(flag):
            if cur == 0:
                run_start = pd.Timestamp(t)
            cur += 1
            if cur > longest:
                longest = cur
                best_start = run_start
                best_end = pd.Timestamp(t)
        else:
            cur = 0
            run_start = None
    return longest, best_start, best_end


def build_metric_c_relative_frame(strategy: pd.Series, benchmark: pd.Series) -> pd.DataFrame:
    """
    Strict Metric C relative NAV frame.

    - Align on strict intersection with dropna (NaN returns excluded, never filled as 0).
    - Rebase both NAVs to 1.0 at the first common observation.
    - relative_nav = strategy_nav / benchmark_nav.
    """
    aligned = pd.concat(
        [strategy.rename("strategy_return"), benchmark.rename("benchmark_return")],
        axis=1,
    ).dropna()
    cols = [
        "strategy_return",
        "benchmark_return",
        "strategy_nav",
        "benchmark_nav",
        "relative_nav",
        "relative_peak",
        "relative_drawdown",
    ]
    if aligned.empty:
        return pd.DataFrame(columns=cols)
    nav_s = (1.0 + aligned["strategy_return"]).cumprod()
    nav_b = (1.0 + aligned["benchmark_return"]).cumprod()
    nav_s = nav_s / float(nav_s.iloc[0])
    nav_b = nav_b / float(nav_b.iloc[0])
    rel = nav_s / nav_b
    peak = rel.cummax()
    return pd.DataFrame(
        {
            "strategy_return": aligned["strategy_return"],
            "benchmark_return": aligned["benchmark_return"],
            "strategy_nav": nav_s,
            "benchmark_nav": nav_b,
            "relative_nav": rel,
            "relative_peak": peak,
            "relative_drawdown": rel / peak - 1.0,
        },
        index=aligned.index,
    )


def metric_c_relative_stats(strategy: pd.Series, benchmark: pd.Series) -> dict:
    """Formal Metric C relative wealth / underwater stats (geometric NAV ratio)."""
    frame = build_metric_c_relative_frame(strategy, benchmark)
    empty = {
        "final_relative_nav": np.nan,
        "relative_max_dd": np.nan,
        "relative_underwater_trading_sessions": np.nan,
        "relative_underwater_calendar_days": np.nan,
        "relative_underwater_months": np.nan,
        "relative_underwater_days": np.nan,
        "current_relative_drawdown": np.nan,
        "currently_underwater": False,
        "n_common_observations": 0,
        "common_start": None,
        "common_end": None,
        "definition": METRIC_C_DEFINITION,
    }
    if len(frame) < 2:
        return empty

    under = frame["relative_drawdown"] < -1e-15
    longest_td, uw_start, uw_end = _longest_under_streak(under)
    if uw_start is not None and uw_end is not None:
        cal_days = int((uw_end - uw_start).days)
        months = _month_span(uw_start, uw_end)
    else:
        cal_days = 0
        months = 0

    return {
        "final_relative_nav": float(frame["relative_nav"].iloc[-1]),
        "relative_max_dd": float(frame["relative_drawdown"].min()),
        "relative_underwater_trading_sessions": float(longest_td),
        "relative_underwater_calendar_days": float(cal_days),
        "relative_underwater_months": float(months),
        "relative_underwater_days": float(longest_td),
        "current_relative_drawdown": float(frame["relative_drawdown"].iloc[-1]),
        "currently_underwater": bool(frame["relative_drawdown"].iloc[-1] < -1e-15),
        "n_common_observations": int(len(frame)),
        "common_start": str(frame.index[0].date()),
        "common_end": str(frame.index[-1].date()),
        "definition": METRIC_C_DEFINITION,
        "frame": frame,
    }


def legacy_arithmetic_excess_relative_path(strategy: pd.Series, benchmark: pd.Series) -> dict:
    """
    DEPRECATED diagnostic only — do NOT use for formal relative wealth / underwater.

    Reproduces the pre-fix approximation:
      (1 + r_strategy - r_benchmark).cumprod()
    """
    aligned = pd.concat([strategy.rename("s"), benchmark.rename("b")], axis=1).dropna()
    if aligned.empty:
        return {
            "method": FORBIDDEN_RELATIVE_WEALTH_FORMULA,
            "final_approx_relative": np.nan,
            "relative_max_dd_approx": np.nan,
            "relative_underwater_trading_sessions_approx": np.nan,
            "deprecated": True,
            "formal_use_forbidden": True,
        }
    excess = aligned["s"] - aligned["b"]
    approx = (1.0 + excess).cumprod()
    approx = approx / float(approx.iloc[0])
    dd = approx / approx.cummax() - 1.0
    under = dd < -1e-15
    longest, _, _ = _longest_under_streak(under)
    return {
        "method": FORBIDDEN_RELATIVE_WEALTH_FORMULA,
        "final_approx_relative": float(approx.iloc[-1]),
        "relative_max_dd_approx": float(dd.min()),
        "relative_underwater_trading_sessions_approx": float(longest),
        "deprecated": True,
        "formal_use_forbidden": True,
        "note": "Not Metric C. May end <1 while true NAV ratio ends >1.",
    }


def arithmetic_annual_excess(strategy: pd.Series, benchmark: pd.Series) -> pd.Series:
    """Calendar-year arithmetic excess: year_return(strategy) - year_return(benchmark)."""
    s = (1 + strategy).resample("YE").prod() - 1
    b = (1 + benchmark).resample("YE").prod() - 1
    return (s - b).dropna()


def relative_to_benchmark(strategy: pd.Series, benchmark: pd.Series) -> dict[str, float]:
    """
    Combined relative analytics.

    Geometric / Metric C fields (formal):
      final_relative_nav, relative_max_dd, relative_underwater_*

    Arithmetic excess fields (not relative wealth):
      arithmetic_excess_mean_ann (= excess_mean), tracking_error, information_ratio
    """
    aligned = pd.concat([strategy.rename("s"), benchmark.rename("b")], axis=1).dropna()
    base = {
        "beta": np.nan,
        "excess_mean": np.nan,
        "arithmetic_excess_mean_ann": np.nan,
        "tracking_error": np.nan,
        "information_ratio": np.nan,
        "up_capture": np.nan,
        "down_capture": np.nan,
        "relative_max_dd": np.nan,
        "relative_underwater_days": np.nan,
        "relative_underwater_trading_sessions": np.nan,
        "relative_underwater_calendar_days": np.nan,
        "relative_underwater_months": np.nan,
        "final_relative_nav": np.nan,
        "current_relative_drawdown": np.nan,
        "relative_definition": METRIC_C_DEFINITION,
    }
    if len(aligned) < 5:
        return base

    cov = aligned["s"].cov(aligned["b"])
    var = aligned["b"].var()
    beta = float(cov / var) if var else np.nan
    excess = aligned["s"] - aligned["b"]
    te = float(excess.std(ddof=1) * np.sqrt(252))
    ir = (
        float(excess.mean() / excess.std(ddof=1) * np.sqrt(252))
        if excess.std(ddof=1)
        else np.nan
    )
    up = aligned["b"] > 0
    down = aligned["b"] < 0
    up_cap = (
        float(aligned.loc[up, "s"].mean() / aligned.loc[up, "b"].mean())
        if up.any() and aligned.loc[up, "b"].mean()
        else np.nan
    )
    down_cap = (
        float(aligned.loc[down, "s"].mean() / aligned.loc[down, "b"].mean())
        if down.any() and aligned.loc[down, "b"].mean()
        else np.nan
    )
    arith_ann = float(excess.mean() * 252)

    mc = metric_c_relative_stats(aligned["s"], aligned["b"])
    return {
        "beta": beta,
        "excess_mean": arith_ann,
        "arithmetic_excess_mean_ann": arith_ann,
        "tracking_error": te,
        "information_ratio": ir,
        "up_capture": up_cap,
        "down_capture": down_cap,
        "relative_max_dd": mc["relative_max_dd"],
        "relative_underwater_days": mc["relative_underwater_trading_sessions"],
        "relative_underwater_trading_sessions": mc["relative_underwater_trading_sessions"],
        "relative_underwater_calendar_days": mc["relative_underwater_calendar_days"],
        "relative_underwater_months": mc["relative_underwater_months"],
        "final_relative_nav": mc["final_relative_nav"],
        "current_relative_drawdown": mc["current_relative_drawdown"],
        "relative_definition": METRIC_C_DEFINITION,
    }


def performance_report(
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    benchmark: pd.Series,
) -> dict:
    gross = _stats(equity["gross_return"])
    net = _stats(equity["net_return"])
    if len(benchmark.dropna()) and benchmark.dropna().abs().median() < 0.2:
        bench_ret = benchmark.reindex(equity.index)
    else:
        bench_ret = benchmark.reindex(equity.index).pct_change(fill_method=None)
    rel = relative_to_benchmark(equity["net_return"], bench_ret)
    abs_uw = underwater_stats(equity["net_return"])
    turnover = float(trades["turnover"].sum() / 2) if not trades.empty and "turnover" in trades else 0.0
    span_years = (
        max((equity.index.max() - equity.index.min()).days / 365.25, 1 / 12) if len(equity) else np.nan
    )
    cost_total = float(trades["cost"].sum()) if not trades.empty and "cost" in trades else 0.0
    return {
        **{f"gross_{k}": v for k, v in gross.items()},
        **{f"net_{k}": v for k, v in net.items()},
        **{f"rel_{k}": v for k, v in rel.items()},
        **{f"abs_{k}": v for k, v in abs_uw.items()},
        "one_way_turnover": turnover,
        "annualized_turnover": turnover / span_years if span_years else np.nan,
        "cost_total": cost_total,
        "cost_drag_cagr_approx": gross["cagr"] - net["cagr"]
        if pd.notna(gross["cagr"]) and pd.notna(net["cagr"])
        else np.nan,
        "avg_holdings": float(equity["n_holdings"].mean()) if "n_holdings" in equity else np.nan,
    }


def window_reports(equity, trades, benchmark, windows: dict) -> dict:
    out = {}
    for name, bounds in windows.items():
        if name == "note":
            continue
        start, end = bounds
        eq = equity.loc[start:end]
        tr = trades
        if not trades.empty and "date" in trades.columns:
            tr = trades[(trades["date"] >= start) & (trades["date"] <= end)]
        out[name] = performance_report(eq, tr, benchmark)
    return out


def ols_alpha(portfolio: pd.Series, factors: pd.DataFrame) -> dict:
    """Regression alpha — not raw excess return."""
    cols = [c for c in ["MKT_RF", "SMB", "HML", "RMW", "CMA", "MOM"] if c in factors.columns]
    frame = pd.concat([portfolio.rename("y"), factors[cols]], axis=1).dropna()
    if len(frame) < 24 or not cols:
        return {"alpha": np.nan, "alpha_t": np.nan, "n": len(frame), "loadings": {}, "model": cols}
    y = frame["y"].to_numpy()
    x = np.column_stack([np.ones(len(frame)), frame[cols].to_numpy()])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    sigma2 = float(resid @ resid / max(len(frame) - x.shape[1], 1))
    se = np.sqrt(np.diag(np.linalg.pinv(x.T @ x) * sigma2))
    return {
        "alpha": float(beta[0]),
        "alpha_annualized": float(beta[0] * 12),
        "alpha_t": float(beta[0] / se[0]) if se[0] else np.nan,
        "n": len(frame),
        "loadings": {name: float(val) for name, val in zip(cols, beta[1:])},
        "model": cols,
    }


def bootstrap_sharpe(returns: pd.Series, n: int = 500, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    arr = returns.dropna().to_numpy()
    if len(arr) < 30:
        return {"mean": np.nan, "p05": np.nan, "p95": np.nan}
    samples = []
    for _ in range(n):
        draw = rng.choice(arr, size=len(arr), replace=True)
        if draw.std(ddof=1) == 0:
            continue
        samples.append(draw.mean() / draw.std(ddof=1) * np.sqrt(252))
    if not samples:
        return {"mean": np.nan, "p05": np.nan, "p95": np.nan}
    return {
        "mean": float(np.mean(samples)),
        "p05": float(np.quantile(samples, 0.05)),
        "p95": float(np.quantile(samples, 0.95)),
    }
