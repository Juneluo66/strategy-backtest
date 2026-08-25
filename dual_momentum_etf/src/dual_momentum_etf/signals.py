"""Month-end dual-momentum signals: returns, SMA filter, and vol-adjusted scores."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def month_end_index(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last trading day of each calendar month present in `dates`."""
    idx = pd.DatetimeIndex(dates).sort_values()
    frame = pd.DataFrame({"date": idx})
    ends = frame.groupby(frame["date"].dt.to_period("M"), sort=True)["date"].max()
    return pd.DatetimeIndex(ends.to_numpy())


def month_end_closes(closes: pd.DataFrame) -> pd.DataFrame:
    ends = month_end_index(closes.index)
    return closes.reindex(ends)


def rolling_month_return(month_closes: pd.DataFrame, months: int) -> pd.DataFrame:
    return month_closes / month_closes.shift(months) - 1.0


def month_sma(month_closes: pd.DataFrame, window: int) -> pd.DataFrame:
    return month_closes.rolling(window, min_periods=window).mean()


def daily_volatility(closes: pd.DataFrame, lookback: int, min_observations: int) -> pd.DataFrame:
    """Trailing daily-return std ending on each calendar day (no annualization)."""
    returns = closes.pct_change(fill_method=None)
    return returns.rolling(lookback, min_periods=min_observations).std(ddof=1)


def build_monthly_signal_panel(
    closes: pd.DataFrame,
    *,
    risk_symbols: list[str],
    weight_5m: float = 0.6,
    weight_12m: float = 0.4,
    sma_months: int = 10,
    vol_lookback: int = 60,
    vol_min_obs: int = 40,
    trend_horizons: tuple[int, int, int] = (3, 6, 12),
) -> pd.DataFrame:
    """
    One row per (month_end, symbol) for risk assets.

    Columns: r3m, r5m, r6m, r12m, score, sigma_60d, adjusted_score,
    above_ma, trend_consistent, close, sma10.
    Trend consistency uses `trend_horizons` (default 3/6/12 months).
    """
    symbols = [s for s in risk_symbols if s in closes.columns]
    me = month_end_closes(closes[symbols])
    h_short, h_mid, h_long = (int(x) for x in trend_horizons)
    r_short = rolling_month_return(me, h_short)
    r5 = rolling_month_return(me, 5)
    r_mid = rolling_month_return(me, h_mid)
    r_long = rolling_month_return(me, h_long)
    # Keep canonical 3/6/12 columns for reporting when horizons match; else also store used horizons.
    r3 = rolling_month_return(me, 3)
    r6 = rolling_month_return(me, 6)
    r12 = rolling_month_return(me, 12)
    sma = month_sma(me, sma_months)
    # Vol as of each month-end close date (uses only history through that day).
    vol_daily = daily_volatility(closes[symbols], vol_lookback, vol_min_obs)
    vol_me = vol_daily.reindex(me.index)

    rows: list[dict] = []
    for date in me.index:
        for symbol in symbols:
            close = me.at[date, symbol]
            if pd.isna(close):
                continue
            r5m = r5.at[date, symbol]
            r12m = r12.at[date, symbol]
            r3m = r3.at[date, symbol]
            r6m = r6.at[date, symbol]
            rs = r_short.at[date, symbol]
            rm = r_mid.at[date, symbol]
            rl = r_long.at[date, symbol]
            score = (
                weight_5m * r5m + weight_12m * r12m
                if pd.notna(r5m) and pd.notna(r12m)
                else np.nan
            )
            sigma = vol_me.at[date, symbol]
            adjusted = score / sigma if pd.notna(score) and pd.notna(sigma) and sigma > 0 else np.nan
            sma_val = sma.at[date, symbol]
            above_ma = bool(pd.notna(sma_val) and close > sma_val)
            trend_ok = bool(
                pd.notna(rs) and pd.notna(rm) and pd.notna(rl) and rs > 0 and rm > 0 and rl > 0
            )
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "close": float(close),
                    "sma10": float(sma_val) if pd.notna(sma_val) else np.nan,
                    "r3m": float(r3m) if pd.notna(r3m) else np.nan,
                    "r5m": float(r5m) if pd.notna(r5m) else np.nan,
                    "r6m": float(r6m) if pd.notna(r6m) else np.nan,
                    "r12m": float(r12m) if pd.notna(r12m) else np.nan,
                    "score": float(score) if pd.notna(score) else np.nan,
                    "sigma_60d": float(sigma) if pd.notna(sigma) else np.nan,
                    "adjusted_score": float(adjusted) if pd.notna(adjusted) else np.nan,
                    "above_ma": above_ma,
                    "trend_consistent": trend_ok,
                    "trend_horizons": f"{h_short}/{h_mid}/{h_long}",
                }
            )
    return pd.DataFrame(rows)


def score_column(vol_adjust: bool) -> str:
    return "adjusted_score" if vol_adjust else "score"


def next_trading_day(dates: pd.DatetimeIndex, signal_date: pd.Timestamp) -> Optional[pd.Timestamp]:
    future = dates[dates > signal_date]
    if len(future) == 0:
        return None
    return pd.Timestamp(future[0])
