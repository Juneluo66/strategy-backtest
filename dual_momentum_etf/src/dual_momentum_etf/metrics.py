"""Performance, turnover, and concentration diagnostics."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _stats(returns: pd.Series) -> dict[str, float]:
    returns = returns.dropna()
    if returns.empty:
        return {"cagr": np.nan, "volatility": np.nan, "sharpe": np.nan, "max_drawdown": np.nan}
    equity = (1 + returns).cumprod()
    years = len(returns) / 252.0
    vol = float(returns.std(ddof=1) * np.sqrt(252)) if len(returns) > 1 else np.nan
    return {
        "cagr": float(equity.iloc[-1] ** (1 / years) - 1) if years > 0 else np.nan,
        "volatility": vol,
        "sharpe": float(returns.mean() / returns.std(ddof=1) * np.sqrt(252))
        if len(returns) > 1 and returns.std(ddof=1)
        else np.nan,
        "max_drawdown": float((equity / equity.cummax() - 1).min()),
    }


def turnover_summary(trades: pd.DataFrame) -> dict[str, float]:
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
        "cost_total": float(trades["cost"].sum()) if "cost" in trades.columns else 0.0,
    }


def concentration_stats(targets: pd.DataFrame) -> dict[str, float]:
    """QQQ dominance and SPY+QQQ co-holding months (pseudo-diversification check)."""
    if targets is None or targets.empty:
        return {
            "months": 0,
            "qqq_held_months": 0,
            "qqq_held_pct": np.nan,
            "spy_qqq_cohold_months": 0,
            "spy_qqq_cohold_pct": np.nan,
        }
    risk = targets[~targets["symbol"].isin(["SGOV", "BIL"])].copy()
    if risk.empty:
        return {
            "months": 0,
            "qqq_held_months": 0,
            "qqq_held_pct": np.nan,
            "spy_qqq_cohold_months": 0,
            "spy_qqq_cohold_pct": np.nan,
        }
    by_month = risk.groupby("signal_date")["symbol"].apply(set)
    months = len(by_month)
    qqq_months = int(sum("QQQ" in s for s in by_month))
    cohold = int(sum(("SPY" in s and "QQQ" in s) for s in by_month))
    return {
        "months": months,
        "qqq_held_months": qqq_months,
        "qqq_held_pct": qqq_months / months if months else np.nan,
        "spy_qqq_cohold_months": cohold,
        "spy_qqq_cohold_pct": cohold / months if months else np.nan,
    }


def performance_report(
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    targets: pd.DataFrame,
    benchmark_close: pd.Series,
) -> dict[str, float]:
    gross = _stats(equity["gross_return"])
    net = _stats(equity["net_return"])
    bench_ret = benchmark_close.reindex(equity.index).pct_change(fill_method=None)
    bench = _stats(bench_ret)
    aligned = pd.concat([equity["net_return"], bench_ret], axis=1).dropna()
    if len(aligned) > 2 and aligned.iloc[:, 1].var():
        beta = float(aligned.iloc[:, 0].cov(aligned.iloc[:, 1]) / aligned.iloc[:, 1].var())
        excess = aligned.iloc[:, 0] - aligned.iloc[:, 1]
        te = float(excess.std(ddof=1) * np.sqrt(252))
        info = float(excess.mean() / excess.std(ddof=1) * np.sqrt(252)) if excess.std(ddof=1) else np.nan
    else:
        beta, te, info = np.nan, np.nan, np.nan
    return {
        **{f"gross_{k}": v for k, v in gross.items()},
        **{f"net_{k}": v for k, v in net.items()},
        "benchmark_cagr": bench["cagr"],
        "benchmark_sharpe": bench["sharpe"],
        "benchmark_max_drawdown": bench["max_drawdown"],
        "realized_beta_to_spy": beta,
        "tracking_error": te,
        "information_ratio": info,
        "average_risk_exposure": float(equity["exposure"].mean()) if "exposure" in equity else np.nan,
        **turnover_summary(trades),
        **concentration_stats(targets),
    }


def window_reports(
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    targets: pd.DataFrame,
    benchmark_close: pd.Series,
    windows: dict,
) -> dict:
    out = {}
    for name, (start, end) in windows.items():
        eq = equity.loc[start:end]
        tr = trades
        if not trades.empty:
            tr = trades[(trades["date"] >= start) & (trades["date"] <= end)]
        tg = targets
        if not targets.empty:
            tg = targets[(targets["execution_date"] >= start) & (targets["execution_date"] <= end)]
        out[name] = performance_report(eq, tr, tg, benchmark_close)
    return out
