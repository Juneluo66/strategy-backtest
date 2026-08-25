"""Cross-sectional factor helpers — no lookahead."""
from __future__ import annotations

import numpy as np
import pandas as pd


def winsorize_cross_section(values: pd.Series, limits: tuple[float, float] = (0.025, 0.975)) -> pd.Series:
    clean = values.dropna()
    if clean.empty:
        return values
    lo, hi = clean.quantile(list(limits))
    return values.clip(lo, hi)


def rank_cross_section(values: pd.Series, ascending: bool = True) -> pd.Series:
    return values.rank(pct=True, ascending=ascending)


def zscore_cross_section(values: pd.Series) -> pd.Series:
    clean = values.dropna()
    if len(clean) < 3 or clean.std(ddof=1) == 0:
        return values * np.nan
    return (values - clean.mean()) / clean.std(ddof=1)


def momentum_12_1(closes: pd.DataFrame, date: pd.Timestamp, trading_days: pd.DatetimeIndex) -> pd.Series:
    """Classic 12-1 momentum: return from t-12m to t-1m on total-return closes.

    Skip the most recent month; use prior 11 months. Not simple 12-month return.
    """
    date = pd.Timestamp(date)
    if date not in trading_days:
        # use last available on or before date
        prior = trading_days[trading_days <= date]
        if prior.empty:
            return pd.Series(dtype=float)
        date = pd.Timestamp(prior[-1])
    # Approximate months by 21 trading days
    loc = trading_days.get_loc(date)
    if isinstance(loc, slice):
        loc = loc.start
    i_skip = loc - 21  # ~1 month ago
    i_start = loc - 21 * 12  # ~12 months ago
    if i_start < 0 or i_skip < 0:
        return pd.Series(np.nan, index=closes.columns)
    start_date = trading_days[i_start]
    skip_date = trading_days[i_skip]
    start_px = closes.loc[start_date]
    skip_px = closes.loc[skip_date]
    return (skip_px / start_px - 1).replace([np.inf, -np.inf], np.nan)


def combine_scores(
    parts: dict[str, pd.Series],
    weights: dict[str, float],
) -> pd.Series:
    """Weighted average of cross-sectional ranks; missing factors drop that weight renormalized."""
    frame = pd.DataFrame({k: rank_cross_section(v) for k, v in parts.items() if k in weights})
    if frame.empty:
        return pd.Series(dtype=float)
    w = pd.Series({k: weights[k] for k in frame.columns}, dtype=float)
    # Per-row renormalize over non-null columns
    mask = frame.notna()
    w_eff = mask.mul(w, axis=1)
    w_sum = w_eff.sum(axis=1).replace(0, np.nan)
    return frame.mul(w, axis=1).sum(axis=1) / w_sum
