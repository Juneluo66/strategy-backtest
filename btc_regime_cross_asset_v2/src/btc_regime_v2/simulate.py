"""Simulate BTC-gated switch between risk-on and risk-off sleeves."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .btc_signals import lean_sma, week_start_equity_dates


def simulate_fixed_pair(
    risk_on_sig: pd.Series,
    on_px: pd.Series,
    off_px: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Weekly boolean risk_on → hold on_px or off_px; adj close C2C."""
    r_on = on_px.pct_change(fill_method=None)
    r_off = off_px.pct_change(fill_method=None)
    cal = on_px.dropna().index.intersection(off_px.dropna().index).sort_values()
    pos = pd.Series(index=cal, dtype=object)
    sig = risk_on_sig.dropna().sort_index()
    starts = list(sig.index)
    for i, ws in enumerate(starts):
        asset = "ON" if bool(sig.loc[ws]) else "OFF"
        end = starts[i + 1] if i + 1 < len(starts) else cal[-1] + pd.Timedelta(days=1)
        mask = (cal >= ws) & (cal < end)
        pos.loc[mask] = asset
    pos = pos.ffill().bfill().fillna("OFF")
    strat = pd.Series(
        np.where(pos == "ON", r_on.reindex(cal), r_off.reindex(cal)),
        index=cal,
        dtype=float,
    )
    return strat.fillna(0.0), pos


def weekly_off_asset_mask(
    trend_px: pd.Series,
    etf_cal: pd.DatetimeIndex,
    week_starts: pd.DatetimeIndex,
    sma_window: int,
) -> pd.Series:
    """Per week_start: True → use trend asset (IEF), False → fallback (SHY)."""
    sma = lean_sma(trend_px.reindex(etf_cal), sma_window)
    trend_on = trend_px.reindex(etf_cal) > sma
    rows = {}
    for ws in week_starts:
        prior = etf_cal[etf_cal < ws]
        if len(prior) == 0:
            continue
        d = prior[-1]
        if pd.isna(trend_on.loc[d]):
            continue
        rows[pd.Timestamp(ws)] = bool(trend_on.loc[d])
    return pd.Series(rows, dtype="boolean")


def simulate_dynamic_off(
    risk_on_sig: pd.Series,
    on_px: pd.Series,
    off_trend_px: pd.Series,
    off_fallback_px: pd.Series,
    *,
    trend_sma: int = 200,
    etf_cal: pd.DatetimeIndex | None = None,
) -> tuple[pd.Series, pd.Series]:
    """BTC OFF → IEF if IEF>SMA200 else SHY; BTC ON → on asset."""
    cal = on_px.dropna().index.intersection(off_fallback_px.dropna().index).sort_values()
    if etf_cal is None:
        etf_cal = cal
    week_starts = week_start_equity_dates(etf_cal)
    off_trend_flag = weekly_off_asset_mask(off_trend_px, etf_cal, week_starts, trend_sma)

    r_on = on_px.pct_change(fill_method=None)
    r_trend = off_trend_px.pct_change(fill_method=None)
    r_fb = off_fallback_px.pct_change(fill_method=None)

    pos = pd.Series(index=cal, dtype=object)
    sig = risk_on_sig.dropna().sort_index()
    starts = list(sig.index)
    for i, ws in enumerate(starts):
        if bool(sig.loc[ws]):
            asset = "ON"
        else:
            use_trend = bool(off_trend_flag.get(ws, False))
            asset = "OFF_TREND" if use_trend else "OFF_FB"
        end = starts[i + 1] if i + 1 < len(starts) else cal[-1] + pd.Timedelta(days=1)
        mask = (cal >= ws) & (cal < end)
        pos.loc[mask] = asset
    pos = pos.ffill().bfill().fillna("OFF_FB")

    strat = pd.Series(index=cal, dtype=float)
    for d in cal:
        a = pos.loc[d]
        if a == "ON":
            strat.loc[d] = r_on.loc[d]
        elif a == "OFF_TREND":
            strat.loc[d] = r_trend.loc[d]
        else:
            strat.loc[d] = r_fb.loc[d]
    return strat.fillna(0.0), pos


def simulate_fixed_pair_costs(
    risk_on_sig: pd.Series,
    on_adj: pd.Series,
    off_adj: pd.Series,
    on_open: pd.Series,
    on_close: pd.Series,
    off_open: pd.Series,
    off_close: pd.Series,
    *,
    cost_bps_rt: float,
) -> tuple[pd.Series, pd.Series]:
    """QC proxy: week-start open→close on switch day; adj close elsewhere; deduct RT cost on switch."""
    cal = on_close.dropna().index.intersection(off_close.dropna().index).sort_values()
    r_on = on_close.pct_change(fill_method=None)
    r_off = off_close.pct_change(fill_method=None)
    pos = pd.Series(index=cal, dtype=object)
    sig = risk_on_sig.dropna().sort_index()
    starts = list(sig.index)
    for i, ws in enumerate(starts):
        asset = "ON" if bool(sig.loc[ws]) else "OFF"
        end = starts[i + 1] if i + 1 < len(starts) else cal[-1] + pd.Timedelta(days=1)
        mask = (cal >= ws) & (cal < end)
        pos.loc[mask] = asset
    pos = pos.ffill().bfill().fillna("OFF")
    strat = pd.Series(
        np.where(pos == "ON", r_on.reindex(cal), r_off.reindex(cal)),
        index=cal,
        dtype=float,
    )
    for ws in starts:
        if ws not in cal:
            continue
        asset = "ON" if bool(sig.loc[ws]) else "OFF"
        o = (on_open if asset == "ON" else off_open).reindex([ws]).iloc[0]
        c = (on_close if asset == "ON" else off_close).reindex([ws]).iloc[0]
        if pd.notna(o) and float(o) != 0.0 and pd.notna(c):
            strat.loc[ws] = float(c) / float(o) - 1.0
    switch = pos.ne(pos.shift(1))
    switch.iloc[0] = False
    if cost_bps_rt > 0:
        strat = strat - switch.astype(float) * (cost_bps_rt / 10000.0)
    return strat.fillna(0.0), pos


def slice_period(r: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    return r.loc[(r.index >= start) & (r.index <= end)].dropna()
