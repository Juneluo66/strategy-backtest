"""Benchmark strategies — buy & hold on shared effective start."""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from data_loader import inception_date
from metrics import compute_metrics


BENCHMARK_TICKERS = ("SPY", "QQQ", "TQQQ", "UPRO", "TECL", "SPXL")


def buy_and_hold_returns(
    closes: pd.DataFrame,
    ticker: str,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.Series:
    if ticker not in closes.columns:
        return pd.Series(dtype=float)
    inc = inception_date(closes, ticker)
    series = closes[ticker].dropna()
    if inc is not None:
        series = series.loc[series.index >= inc]
    if start:
        series = series.loc[series.index >= pd.Timestamp(start)]
    if end:
        series = series.loc[series.index <= pd.Timestamp(end)]
    return series.pct_change().dropna()


def benchmark_grid(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    initial_cash: float = 100_000.0,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for ticker in BENCHMARK_TICKERS:
        if ticker not in closes.columns:
            continue
        inc = inception_date(closes, ticker)
        eff_start = pd.Timestamp(start) if start else closes.index.min()
        if inc is not None and inc > eff_start:
            eff_start = inc
        rets = buy_and_hold_returns(closes, ticker, start=str(eff_start.date()), end=end)
        if rets.empty:
            continue
        equity = pd.DataFrame({"net_return": rets, "gross_return": rets})
        equity["equity_net"] = (1 + equity["net_return"]).cumprod()
        equity["equity_gross"] = equity["equity_net"]
        equity["exposure"] = 1.0
        equity["cash_ratio"] = 0.0
        metrics = compute_metrics(equity, pd.DataFrame({"date": [], "turnover": []}), label=ticker)
        results[ticker] = {
            "equity": equity,
            "metrics": metrics,
            "inception": str(inc.date()) if inc else None,
            "start_used": str(eff_start.date()),
        }
    return results
