"""Frozen BTC SMA50 + MOM20 weekly gate (QC week-start proxy)."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .config import V2Config
from .data import fetch_bitfinex_btc


def lean_roc(close: pd.Series, period: int) -> pd.Series:
    return (close / close.shift(period) - 1.0) * 100.0


def lean_sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(period, min_periods=period).mean()


def week_start_equity_dates(etf_index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(1, index=pd.DatetimeIndex(etf_index).sort_values())
    week = s.index.to_series().dt.isocalendar()
    key = week["year"].astype(str) + "-" + week["week"].astype(str).str.zfill(2)
    first = s.groupby(key.values).apply(lambda g: g.index.min())
    return pd.DatetimeIndex(sorted(first.values))


def btc_asof_monday_8am_et(
    btc_close_utc_daily: pd.Series, monday: pd.Timestamp
) -> tuple[Optional[float], Optional[pd.Timestamp]]:
    m = pd.Timestamp(monday).tz_localize(None).normalize()
    avail = btc_close_utc_daily.loc[btc_close_utc_daily.index < m].dropna()
    if avail.empty:
        return None, None
    return float(avail.iloc[-1]), pd.Timestamp(avail.index[-1])


def qc_weekly_btc_signals(
    btc_close: pd.Series,
    week_starts: pd.DatetimeIndex,
    *,
    sma_n: int,
    roc_n: int,
) -> pd.DataFrame:
    sma = lean_sma(btc_close, sma_n)
    roc = lean_roc(btc_close, roc_n)
    rows = []
    for ws in week_starts:
        px, asof = btc_asof_monday_8am_et(btc_close, ws)
        if px is None or asof is None or asof not in sma.index or pd.isna(sma.loc[asof]) or pd.isna(roc.loc[asof]):
            rows.append({"week_start": pd.Timestamp(ws), "risk_on": pd.NA})
            continue
        rows.append(
            {
                "week_start": pd.Timestamp(ws),
                "risk_on": bool(px > float(sma.loc[asof]) and float(roc.loc[asof]) > 0.0),
            }
        )
    return pd.DataFrame(rows)


def load_btc_weekly_signal(config: V2Config, etf_cal: pd.DatetimeIndex) -> pd.Series:
    gate = config.raw["btc_gate"]
    bf = fetch_bitfinex_btc(config)
    week_starts = week_start_equity_dates(etf_cal)
    sigs = qc_weekly_btc_signals(
        bf["Close"].astype(float),
        week_starts,
        sma_n=int(gate["sma_window"]),
        roc_n=int(gate["momentum_window"]),
    )
    valid = sigs.dropna(subset=["risk_on"])
    t0 = pd.Timestamp(config.raw["data"]["effective_start"])
    valid = valid[valid["week_start"] >= t0]
    return valid.set_index("week_start")["risk_on"].astype("boolean")
