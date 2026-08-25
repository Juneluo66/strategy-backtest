"""Calendar helpers for month-end signal / next-open execution."""
from __future__ import annotations

from typing import Optional

import pandas as pd


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
    """Return the n-th trading session strictly after `date` (n>=1)."""
    if n < 1:
        raise ValueError("n must be >= 1")
    cur = pd.Timestamp(date)
    for _ in range(n):
        nxt = next_trading_day(calendar, cur)
        if nxt is None:
            return None
        cur = nxt
    return cur
