"""Performance, turnover, cost and benchmark diagnostics."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _stats(returns: pd.Series) -> dict[str, float]:
    returns = returns.dropna()
    if returns.empty:
        return {"cagr": np.nan, "volatility": np.nan, "sharpe": np.nan, "max_drawdown": np.nan}
    equity = (1 + returns).cumprod()
    years = len(returns) / 252
    return {
        "cagr": float(equity.iloc[-1] ** (1 / years) - 1) if years else np.nan,
        "volatility": float(returns.std(ddof=1) * np.sqrt(252)),
        "sharpe": float(returns.mean() / returns.std(ddof=1) * np.sqrt(252))
        if returns.std(ddof=1)
        else np.nan,
        "max_drawdown": float((equity / equity.cummax() - 1).min()),
    }


def turnover_summary(trades: pd.DataFrame) -> dict[str, float]:
    if trades.empty:
        return {"one_way_turnover": 0.0, "annualized_turnover": 0.0, "cost_total": 0.0}
    daily = trades.groupby("date")["turnover"].sum()
    span_years = max((pd.to_datetime(daily.index).max() - pd.to_datetime(daily.index).min()).days / 365.25, 1 / 12)
    return {
        "one_way_turnover": float(daily.sum() / 2),
        "annualized_turnover": float(daily.sum() / 2 / span_years),
        "cost_total": float(trades["cost"].sum()),
    }


def performance_report(results: pd.DataFrame, trades: pd.DataFrame, benchmark: pd.Series) -> dict[str, float]:
    gross = _stats(results["gross_return"])
    net = _stats(results["net_return"])
    benchmark_return = benchmark.reindex(results.index).pct_change()
    benchmark_stats = _stats(benchmark_return)
    aligned = pd.concat([results["net_return"], benchmark_return], axis=1).dropna()
    beta = (
        float(aligned.iloc[:, 0].cov(aligned.iloc[:, 1]) / aligned.iloc[:, 1].var())
        if len(aligned) > 2 and aligned.iloc[:, 1].var()
        else np.nan
    )
    return {
        **{f"gross_{key}": value for key, value in gross.items()},
        **{f"net_{key}": value for key, value in net.items()},
        "cost_drag_cagr": gross["cagr"] - net["cagr"],
        "benchmark_sharpe": benchmark_stats["sharpe"],
        "realized_beta_to_spy": beta,
        "average_exposure": float(results["exposure"].mean()),
        **turnover_summary(trades),
    }


def window_reports(results: pd.DataFrame, trades: pd.DataFrame, benchmark: pd.Series, windows: dict) -> dict:
    return {
        name: performance_report(
            results.loc[start:end], trades.loc[(trades["date"] >= start) & (trades["date"] <= end)], benchmark
        )
        for name, (start, end) in windows.items()
    }
