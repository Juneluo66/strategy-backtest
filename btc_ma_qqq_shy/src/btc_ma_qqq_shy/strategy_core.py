"""Generalized signal → QQQ/SHY weekly strategy helpers."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import summary_stats
from .signals import btc_daily_signal, build_position_series


def risk_on_signal(price: pd.Series, *, sma_window: int, momentum_window: int) -> pd.Series:
    """Same rule as BTC gate, on an arbitrary price series."""
    feat = btc_daily_signal(price, sma_window=sma_window, momentum_window=momentum_window)
    return feat["risk_on"]


def _align_signal_to_calendar(sig: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    """Forward-fill signal onto ETF sessions (handles crypto weekends)."""
    union = calendar.union(sig.dropna().index).sort_values()
    return sig.reindex(union).ffill().reindex(calendar)


def run_gated_strategy(
    signal_price: pd.Series,
    qqq: pd.Series,
    shy: pd.Series,
    *,
    sma_window: int,
    momentum_window: int,
    audit_start: pd.Timestamp,
) -> dict:
    """Weekly gate on signal_price → hold QQQ else SHY; next-session execution."""
    etf = pd.concat([qqq.rename("QQQ"), shy.rename("SHY")], axis=1).dropna()
    sig = risk_on_signal(signal_price, sma_window=sma_window, momentum_window=momentum_window)
    sig_etf = _align_signal_to_calendar(sig, etf.index)

    first = sig.dropna().index.min()
    if pd.isna(first):
        raise ValueError("no valid signal")
    effective = max(pd.Timestamp(audit_start), pd.Timestamp(first))

    position = build_position_series(
        sig_etf, etf.index, risk_on_asset="QQQ", risk_off_asset="SHY"
    )
    rets = etf.pct_change()
    on = (position == "QQQ").to_numpy()
    strat = pd.Series(
        np.where(on, rets["QQQ"].to_numpy(), rets["SHY"].to_numpy()),
        index=etf.index,
        name="strategy",
    ).fillna(0.0)

    mask = etf.index >= effective
    s_ret = strat.loc[mask].iloc[1:]
    q_ret = rets["QQQ"].loc[mask].iloc[1:]
    return {
        "effective_start": effective,
        "strategy_return": s_ret,
        "qqq_return": q_ret,
        "position": position.loc[mask],
        "stats_strategy": summary_stats(s_ret),
        "stats_qqq": summary_stats(q_ret),
        "signal_on_etf": sig_etf.loc[mask],
    }
