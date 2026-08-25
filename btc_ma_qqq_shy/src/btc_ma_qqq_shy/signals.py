"""Signal: BTC above SMA50 and 20-day momentum positive; weekly decision."""
from __future__ import annotations

import pandas as pd


def btc_daily_signal(btc: pd.Series, *, sma_window: int, momentum_window: int) -> pd.DataFrame:
    """Daily BTC features and boolean risk-on flag (same-day knowledge)."""
    px = btc.astype(float).dropna().sort_index()
    sma = px.rolling(sma_window, min_periods=sma_window).mean()
    mom = px / px.shift(momentum_window) - 1.0
    above = px > sma
    mom_pos = mom > 0.0
    valid = sma.notna() & mom.notna()
    risk_on = (above & mom_pos).where(valid, other=pd.NA)
    return pd.DataFrame(
        {
            "btc": px,
            "sma50": sma,
            "mom20": mom,
            "above_sma": above.where(valid, other=pd.NA),
            "mom_pos": mom_pos.where(valid, other=pd.NA),
            "risk_on": risk_on,
        }
    )


def weekly_decision_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last available session of each ISO year-week."""
    s = pd.Series(1, index=pd.DatetimeIndex(index).sort_values())
    week = s.index.to_series().dt.isocalendar()
    key = week["year"].astype(str) + "-" + week["week"].astype(str).str.zfill(2)
    # last index per week key
    last = s.groupby(key.values).apply(lambda g: g.index.max())
    return pd.DatetimeIndex(sorted(last.values))


def build_position_series(
    risk_on_daily: pd.Series,
    etf_index: pd.DatetimeIndex,
    *,
    risk_on_asset: str,
    risk_off_asset: str,
) -> pd.Series:
    """
    Week-end signal → position applies from the *next* ETF session through the
    session of the following week-end decision (inclusive of holding returns).

    Before first usable (non-NA) signal: hold risk_off.
    """
    etf_index = pd.DatetimeIndex(etf_index).sort_values()
    # Boolean with NA preserved
    sig = risk_on_daily.reindex(etf_index)
    decisions = weekly_decision_dates(etf_index)
    decisions = pd.DatetimeIndex(
        [d for d in decisions if d in sig.index and pd.notna(sig.loc[d])]
    )

    pos = pd.Series(index=etf_index, dtype=object)
    if len(decisions) == 0:
        return pos.fillna(risk_off_asset)

    for i, d in enumerate(decisions):
        signal = bool(sig.loc[d])
        asset = risk_on_asset if signal else risk_off_asset
        after = etf_index[etf_index > d]
        if len(after) == 0:
            continue
        start = after[0]
        end = decisions[i + 1] if i + 1 < len(decisions) else etf_index[-1]
        mask = (etf_index >= start) & (etf_index <= end)
        pos.loc[mask] = asset

    return pos.fillna(risk_off_asset)
