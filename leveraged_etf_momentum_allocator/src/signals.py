"""Momentum signal engine — parameterized, not hard-coded to original rules."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


LOOKBACK_PRESETS = {
    "1m": 21,
    "3m": 63,
    "6m": 126,
    "12m": 252,
}


def resolve_lookback(method: str, lookback_days: Optional[int]) -> int:
    if method == "12-1":
        return 252  # nominal lookback for metadata; calculate() uses fixed offsets
    if lookback_days is not None:
        return int(lookback_days)
    if method in LOOKBACK_PRESETS:
        return LOOKBACK_PRESETS[method]
    raise ValueError(f"lookback_days required for method={method!r}")


class MomentumSignal:
    """Cross-sectional momentum using only history through signal_date."""

    def __init__(
        self,
        method: str,
        lookback_days: Optional[int],
        skip_recent_days: int = 0,
    ):
        self.method = str(method)
        self.lookback_days = resolve_lookback(method, lookback_days)
        self.skip_recent_days = int(skip_recent_days)

    def _price_at_offset(
        self,
        prices: pd.Series,
        signal_date: pd.Timestamp,
        offset: int,
    ) -> Optional[float]:
        """Return price at signal_date minus `offset` trading days (inclusive history)."""
        history = prices.loc[:signal_date].dropna()
        if len(history) <= offset:
            return None
        return float(history.iloc[-(offset + 1)])

    def calculate(self, prices: pd.Series, signal_date: pd.Timestamp) -> Optional[float]:
        """Compute momentum for one ticker through signal_date close."""
        if signal_date not in prices.index:
            # Use last available date on or before signal_date
            history = prices.loc[:signal_date].dropna()
            if history.empty:
                return None
            signal_date = pd.Timestamp(history.index[-1])
        else:
            if pd.isna(prices.loc[signal_date]):
                return None

        if self.method == "total_return":
            p_end = self._price_at_offset(prices, signal_date, self.skip_recent_days)
            p_start = self._price_at_offset(
                prices, signal_date, self.skip_recent_days + self.lookback_days
            )
            if p_end is None or p_start is None or p_start == 0:
                return None
            return p_end / p_start - 1.0

        if self.method == "12-1":
            p_end = self._price_at_offset(prices, signal_date, 21)
            p_start = self._price_at_offset(prices, signal_date, 21 + 252)
            if p_end is None or p_start is None or p_start == 0:
                return None
            return p_end / p_start - 1.0

        if self.method in LOOKBACK_PRESETS:
            lb = LOOKBACK_PRESETS[self.method]
            p_end = self._price_at_offset(prices, signal_date, self.skip_recent_days)
            p_start = self._price_at_offset(prices, signal_date, self.skip_recent_days + lb)
            if p_end is None or p_start is None or p_start == 0:
                return None
            return p_end / p_start - 1.0

        raise ValueError(f"unsupported momentum method: {self.method}")

    def calculate_panel(
        self,
        closes: pd.DataFrame,
        signal_date: pd.Timestamp,
        tickers: list[str],
    ) -> pd.Series:
        scores: dict[str, float] = {}
        for ticker in tickers:
            if ticker not in closes.columns:
                continue
            score = self.calculate(closes[ticker], signal_date)
            if score is not None and np.isfinite(score):
                scores[ticker] = score
        return pd.Series(scores, dtype=float)


def month_end_index(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(dates).sort_values()
    frame = pd.DataFrame({"date": idx})
    ends = frame.groupby(frame["date"].dt.to_period("M"), sort=True)["date"].max()
    return pd.DatetimeIndex(ends.to_numpy())


def next_trading_day(calendar: pd.DatetimeIndex, date: pd.Timestamp) -> Optional[pd.Timestamp]:
    future = calendar[calendar > pd.Timestamp(date)]
    return None if future.empty else pd.Timestamp(future[0])


def trading_day_plus_n(
    calendar: pd.DatetimeIndex, date: pd.Timestamp, n: int
) -> Optional[pd.Timestamp]:
    if n < 1:
        raise ValueError("n must be >= 1")
    cur = pd.Timestamp(date)
    for _ in range(n):
        nxt = next_trading_day(calendar, cur)
        if nxt is None:
            return None
        cur = nxt
    return cur


def rebalance_dates(
    calendar: pd.DatetimeIndex,
    frequency: str,
) -> pd.DatetimeIndex:
    freq = frequency.lower()
    if freq in {"monthly", "month_end", "month-end"}:
        return month_end_index(calendar)
    if freq in {"weekly", "week_end", "week-end"}:
        idx = pd.DatetimeIndex(calendar).sort_values()
        frame = pd.DataFrame({"date": idx})
        ends = frame.groupby(frame["date"].dt.to_period("W-FRI"), sort=True)["date"].max()
        return pd.DatetimeIndex(ends.to_numpy())
    if freq in {"quarterly", "quarter_end"}:
        idx = pd.DatetimeIndex(calendar).sort_values()
        frame = pd.DataFrame({"date": idx})
        ends = frame.groupby(frame["date"].dt.to_period("Q"), sort=True)["date"].max()
        return pd.DatetimeIndex(ends.to_numpy())
    if freq == "daily":
        return pd.DatetimeIndex(calendar)
    raise ValueError(f"unsupported rebalance frequency: {frequency}")
