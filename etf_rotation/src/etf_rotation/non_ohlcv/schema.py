"""Strict PIT contract for raw non-OHLCV observations."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = (
    "code",
    "observation_date",
    "available_at",
    "value",
    "source",
    "source_version",
    "retrieved_at",
)


def validate_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate raw observations without inventing values or availability dates."""
    missing = set(REQUIRED_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"non-OHLCV data missing columns: {sorted(missing)}")
    out = frame.loc[:, REQUIRED_COLUMNS].copy()
    for column in ("observation_date", "available_at", "retrieved_at"):
        out[column] = pd.to_datetime(out[column], errors="coerce")
    out["code"] = out["code"].astype(str).str.zfill(6)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    if out[["observation_date", "available_at", "retrieved_at"]].isna().any().any():
        raise ValueError("non-OHLCV timestamps must be parseable")
    if (out["available_at"] < out["observation_date"]).any():
        raise ValueError("available_at cannot precede observation_date")
    duplicates = out.duplicated(["code", "observation_date", "source_version"])
    if duplicates.any():
        raise ValueError("duplicate code/observation_date/source_version observations")
    return out.sort_values(["code", "observation_date", "available_at"]).reset_index(drop=True)


def write_observations(frame: pd.DataFrame, path: Path) -> None:
    """Persist a validated versioned source snapshot, never filling missing values."""
    path.parent.mkdir(parents=True, exist_ok=True)
    validate_observations(frame).to_parquet(path, index=False)


def pit_values(frame: pd.DataFrame, signal_dates: pd.Series) -> pd.DataFrame:
    """Return only observations visible no later than each signal date."""
    source = validate_observations(frame)
    dates = pd.DataFrame({"signal_date": pd.to_datetime(signal_dates).drop_duplicates()})
    merged = dates.merge(source, how="cross")
    return merged.loc[merged["available_at"] <= merged["signal_date"]].copy()
