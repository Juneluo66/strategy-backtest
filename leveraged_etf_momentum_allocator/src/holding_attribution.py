"""Holding-level attribution — PnL by ticker."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def holding_attribution(
    equity: pd.DataFrame,
    signal_log: pd.DataFrame,
    trades: pd.DataFrame,
) -> pd.DataFrame:
    """Per-ticker holding statistics from signal log and trades."""
    if signal_log.empty:
        return pd.DataFrame()

    targets = signal_log["target"].unique()
    rows: list[dict[str, Any]] = []
    log = signal_log.set_index("date")
    merged = equity.join(log[["target"]], how="inner")

    for ticker in targets:
        mask = merged["target"] == ticker
        days = int(mask.sum())
        rets = merged.loc[mask, "net_return"]
        if "target_changed" in signal_log.columns:
            entries = int(
                signal_log.loc[
                    (signal_log["target"] == ticker) & signal_log["target_changed"],
                    "target_changed",
                ].sum()
            )
        else:
            entries = days

        trade_returns = _round_trip_returns(trades, ticker)
        rows.append(
            {
                "ticker": ticker,
                "days_held": days,
                "portfolio_time_pct": days / len(merged),
                "number_of_entries": entries,
                "total_pnl_proxy": float(rets.sum()),
                "cagr_contribution_approx": _cagr(rets),
                "average_daily_return": float(rets.mean()) if len(rets) else np.nan,
                "average_trade_return": float(np.mean(trade_returns)) if trade_returns else np.nan,
                "median_trade_return": float(np.median(trade_returns)) if trade_returns else np.nan,
                "win_rate_daily": float((rets > 0).mean()) if len(rets) else np.nan,
                "win_rate_trades": float(np.mean([r > 0 for r in trade_returns])) if trade_returns else np.nan,
                "worst_trade": float(min(trade_returns)) if trade_returns else np.nan,
                "best_trade": float(max(trade_returns)) if trade_returns else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("total_pnl_proxy", ascending=False)


def _round_trip_returns(trades: pd.DataFrame, ticker: str) -> list[float]:
    if trades.empty:
        return []
    legs = trades[trades["ticker"] == ticker].sort_values("date")
    returns: list[float] = []
    buy_px = None
    for _, row in legs.iterrows():
        if row["side"] == "buy":
            buy_px = float(row["execution_price"])
        elif row["side"] == "sell" and buy_px and buy_px > 0:
            ret = float(row["execution_price"]) / buy_px - 1
            returns.append(ret)
            buy_px = None
    return returns


def _cagr(rets: pd.Series) -> float:
    r = rets.dropna()
    if r.empty:
        return float("nan")
    years = len(r) / 252
    return float((1 + r).prod() ** (1 / years) - 1) if years > 0 else float("nan")
