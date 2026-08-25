"""Adapters for verified exchange margin-detail fields.

This module deliberately exposes raw observations only. Factor calculation and
production cache writes remain blocked until a trading-calendar-derived
``available_at`` timestamp is supplied by the caller.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from etf_rotation.non_ohlcv.schema import validate_observations


def fetch_exchange_detail(date: str, exchange: str) -> pd.DataFrame:
    """Fetch one official exchange detail snapshot through AkShare."""
    import akshare as ak

    if exchange == "SSE":
        return ak.stock_margin_detail_sse(date=date)
    if exchange == "SZSE":
        return ak.stock_margin_detail_szse(date=date)
    raise ValueError("exchange must be SSE or SZSE")


def normalize_margin_detail(
    frame: pd.DataFrame,
    *,
    exchange: str,
    available_at: pd.Timestamp,
    source_version: str,
) -> pd.DataFrame:
    """Normalize `rzye` and `rzmre` without treating absent securities as zero."""
    source_columns = {
        "标的证券代码": "code",
        "信用交易日期": "observation_date",
        "融资余额": "rzye",
        "融资买入额": "rzmre",
    }
    missing = set(source_columns).difference(frame.columns)
    if missing:
        raise ValueError(f"{exchange} margin detail missing columns: {sorted(missing)}")
    raw = frame.rename(columns=source_columns)[list(source_columns.values())].copy()
    raw["code"] = raw["code"].astype(str).str.zfill(6)
    raw["observation_date"] = pd.to_datetime(raw["observation_date"])
    raw["available_at"] = pd.Timestamp(available_at)
    raw["source"] = f"AkShare/{exchange}_margin_detail"
    raw["source_version"] = source_version
    raw["retrieved_at"] = datetime.now(timezone.utc)
    rows = []
    for field in ("rzye", "rzmre"):
        subset = raw[["code", "observation_date", "available_at", field, "source", "source_version", "retrieved_at"]]
        subset = subset.rename(columns={field: "value"})
        subset["field"] = field
        rows.append(subset)
    result = pd.concat(rows, ignore_index=True)
    # validate separately because `field` distinguishes same date/code observations.
    validated = []
    for field, subset in result.groupby("field", sort=True):
        checked = validate_observations(subset.drop(columns="field"))
        checked["field"] = field
        validated.append(checked)
    return pd.concat(validated, ignore_index=True)
