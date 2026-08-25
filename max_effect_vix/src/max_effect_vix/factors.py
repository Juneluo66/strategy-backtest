"""Point-in-time MAX factor and VIX sizing calculations."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def max_factor(returns: pd.Series, lookback: int = 21, top_returns: int = 5) -> pd.Series:
    """Mean of the top returns in each trailing completed trading-day window."""
    if not 0 < top_returns <= lookback:
        raise ValueError("top_returns must be in [1, lookback]")

    def top_mean(window: np.ndarray) -> float:
        values = window[np.isfinite(window)]
        return float(np.mean(np.partition(values, -top_returns)[-top_returns:])) if len(values) >= top_returns else np.nan

    return returns.rolling(lookback, min_periods=lookback).apply(top_mean, raw=True).rename("max_factor")


def vix_leverage(vix: Optional[float], mode: str = "original") -> float:
    """QC Research 20886 leverage rule, using the last known VIX close."""
    if mode == "none":
        return 1.0
    if vix is None or not np.isfinite(vix):
        return 1.0
    original = 1.5 if vix <= 15 else 1.0 if vix >= 30 else 1.5 - ((vix - 15) / 15) * 0.5
    if mode == "deleverage_only":
        # Normalize the published 1.0–1.5 range to 2/3–1.0: no borrowing,
        # but retain a genuine reduction in high-VIX regimes.
        return float(original / 1.5)
    if mode != "original":
        raise ValueError(f"unknown VIX mode: {mode}")
    return float(original)


def monthly_signal_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Return last completed trading date before each month's first execution day."""
    dates = pd.DatetimeIndex(index).sort_values().unique()
    frame = pd.DataFrame(index=dates)
    first_days = frame.groupby([dates.year, dates.month]).head(1).index
    positions = dates.get_indexer(first_days)
    return dates[positions[positions > 0] - 1]
