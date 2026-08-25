"""Compute v8 non-OHLCV factors from PIT observations; never invent values."""
from __future__ import annotations

import numpy as np
import pandas as pd

from etf_rotation.non_ohlcv.schema import validate_observations

EPS = 1e-10


def panel_from_observations(
    observations: pd.DataFrame, signal_dates: pd.DatetimeIndex, codes: list[str]
) -> pd.DataFrame:
    """Build a code×date panel using only observations with available_at <= signal date."""
    source = validate_observations(observations)
    columns: dict[str, pd.Series] = {}
    for code in codes:
        subset = source.loc[source["code"].eq(code), ["available_at", "value"]].sort_values(
            "available_at"
        )
        left = pd.DataFrame({"available_at": pd.to_datetime(signal_dates)}).sort_values(
            "available_at"
        )
        if subset.empty:
            columns[code] = pd.Series(np.nan, index=signal_dates, name=code)
            continue
        joined = pd.merge_asof(left, subset, on="available_at", direction="backward")
        columns[code] = pd.Series(joined["value"].to_numpy(), index=signal_dates, name=code)
    return pd.DataFrame(columns)


def share_change(share_panel: pd.DataFrame, window: int) -> pd.DataFrame:
    """Relative share change; missing or zero prior share remains NaN."""
    prior = share_panel.shift(window)
    change = (share_panel - prior) / (prior.abs() + EPS)
    return change.where(prior.abs() > EPS)


def margin_change(rzye: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """Relative financing-balance change; absent ETFs stay NaN."""
    prior = rzye.shift(window)
    change = (rzye - prior) / (prior.abs() + EPS)
    return change.where(prior.abs() > EPS)


def margin_buy_ratio(rzmre: pd.DataFrame, close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """rzmre / (close * volume); zero or missing turnover stays NaN."""
    amount = close * volume
    return rzmre / amount.where(amount.abs() > EPS)
