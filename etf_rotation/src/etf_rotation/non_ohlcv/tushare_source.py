"""TuShare adapters for daily margin and ETF share observations."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Callable

import pandas as pd

from etf_rotation.non_ohlcv.schema import validate_observations

SOURCE_NAME = "TuShare"
# Documented exchange refresh: prior session published ~08:30 next calendar/trading day.
_DEFAULT_AVAILABLE_HOUR = 8
_DEFAULT_AVAILABLE_MINUTE = 30


class TuShareTokenError(RuntimeError):
    """Raised when TUSHARE_TOKEN is missing or unusable."""


def resolve_tushare_token(explicit: str | None = None) -> str:
    """Resolve token from argument or environment; never invent credentials."""
    token = (explicit or os.environ.get("TUSHARE_TOKEN") or "").strip()
    if not token:
        raise TuShareTokenError(
            "TUSHARE_TOKEN is not set. Export a TuShare Pro token before "
            "`etf-rotation fetch-non-ohlcv --full`. No empty parquet will be written."
        )
    return token


def to_ts_code(code: str) -> str:
    """Map 6-digit A-share ETF codes to TuShare ts_code."""
    code = str(code).zfill(6)
    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def from_ts_code(ts_code: str) -> str:
    return str(ts_code).split(".", maxsplit=1)[0].zfill(6)


def make_pro_api(token: str | None = None):
    """Create a TuShare Pro API client."""
    import tushare as ts

    return ts.pro_api(resolve_tushare_token(token))


def next_session_available_at(
    observation_dates: pd.Series,
    trading_calendar: pd.DatetimeIndex | None = None,
) -> pd.Series:
    """Conservative PIT: data for T is visible at next session 08:30."""
    obs = pd.to_datetime(observation_dates)
    if trading_calendar is None or len(trading_calendar) == 0:
        available = pd.Series(obs + pd.Timedelta(days=1), index=obs.index)
    else:
        calendar = pd.DatetimeIndex(pd.to_datetime(trading_calendar)).normalize().unique().sort_values()
        positions = calendar.searchsorted(obs.dt.normalize(), side="right")
        values = []
        for pos, stamp in zip(positions, obs):
            if pos < len(calendar):
                values.append(calendar[pos])
            else:
                values.append(pd.Timestamp(stamp).normalize() + pd.Timedelta(days=1))
        available = pd.Series(pd.to_datetime(values), index=obs.index)
    return available.dt.normalize() + pd.Timedelta(
        hours=_DEFAULT_AVAILABLE_HOUR, minutes=_DEFAULT_AVAILABLE_MINUTE
    )


def _rows_from_field(
    frame: pd.DataFrame,
    *,
    field: str,
    source_version: str,
    trading_calendar: pd.DatetimeIndex | None,
    retrieved_at: datetime,
) -> pd.DataFrame:
    if frame is None or frame.empty or field not in frame.columns:
        return pd.DataFrame(columns=[
            "code", "observation_date", "available_at", "value",
            "source", "source_version", "retrieved_at",
        ])
    out = pd.DataFrame({
        "code": frame["ts_code"].map(from_ts_code),
        "observation_date": pd.to_datetime(frame["trade_date"]),
        "value": pd.to_numeric(frame[field], errors="coerce"),
        "source": f"{SOURCE_NAME}/{field}",
        "source_version": source_version,
        "retrieved_at": retrieved_at,
    })
    out = out.loc[out["value"].notna()].copy()
    if out.empty:
        return out
    out["available_at"] = next_session_available_at(out["observation_date"], trading_calendar)
    return validate_observations(out)


def fetch_margin_detail_code(
    pro,
    code: str,
    *,
    start_date: str,
    end_date: str,
    source_version: str,
    trading_calendar: pd.DatetimeIndex | None = None,
    retrieved_at: datetime | None = None,
) -> dict[str, pd.DataFrame]:
    """Fetch rzye/rzmre observations for one ETF. Empty dict values stay empty frames."""
    retrieved = retrieved_at or datetime.now(timezone.utc)
    raw = pro.margin_detail(
        ts_code=to_ts_code(code),
        start_date=start_date,
        end_date=end_date,
        fields="trade_date,ts_code,rzye,rzmre",
    )
    return {
        "rzye": _rows_from_field(
            raw, field="rzye", source_version=source_version,
            trading_calendar=trading_calendar, retrieved_at=retrieved,
        ),
        "rzmre": _rows_from_field(
            raw, field="rzmre", source_version=source_version,
            trading_calendar=trading_calendar, retrieved_at=retrieved,
        ),
    }


def fetch_etf_share_size_code(
    pro,
    code: str,
    *,
    start_date: str,
    end_date: str,
    source_version: str,
    trading_calendar: pd.DatetimeIndex | None = None,
    retrieved_at: datetime | None = None,
) -> pd.DataFrame:
    """Fetch daily total_share (万份). Does not fall back to quarterly fund scale."""
    retrieved = retrieved_at or datetime.now(timezone.utc)
    raw = pro.etf_share_size(
        ts_code=to_ts_code(code),
        start_date=start_date,
        end_date=end_date,
        fields="trade_date,ts_code,total_share",
    )
    return _rows_from_field(
        raw, field="total_share", source_version=source_version,
        trading_calendar=trading_calendar, retrieved_at=retrieved,
    )


def download_universe_observations(
    codes: list[str],
    *,
    start_date: str,
    end_date: str,
    token: str | None = None,
    trading_calendar: pd.DatetimeIndex | None = None,
    sleep_seconds: float = 0.35,
    source_version: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, pd.DataFrame]:
    """Download margin + share observations for the ETF universe.

    Returns non-empty validated frames only for fields that returned rows.
    Never invents zeros for absent securities.
    """
    pro = make_pro_api(token)
    version = source_version or datetime.now(timezone.utc).strftime("tushare_%Y%m%dT%H%M%SZ")
    retrieved = datetime.now(timezone.utc)
    buckets: dict[str, list[pd.DataFrame]] = {"rzye": [], "rzmre": [], "total_share": []}
    errors: list[dict[str, str]] = []

    for code in codes:
        if progress:
            progress(f"margin+share {code}")
        try:
            margin = fetch_margin_detail_code(
                pro, code, start_date=start_date, end_date=end_date,
                source_version=version, trading_calendar=trading_calendar, retrieved_at=retrieved,
            )
            for field, frame in margin.items():
                if not frame.empty:
                    buckets[field].append(frame)
        except Exception as exc:  # noqa: BLE001 - persist per-code remote failure
            errors.append({"code": code, "field": "margin_detail", "error": str(exc)})
        try:
            shares = fetch_etf_share_size_code(
                pro, code, start_date=start_date, end_date=end_date,
                source_version=version, trading_calendar=trading_calendar, retrieved_at=retrieved,
            )
            if not shares.empty:
                buckets["total_share"].append(shares)
        except Exception as exc:  # noqa: BLE001 - persist per-code remote failure
            errors.append({"code": code, "field": "etf_share_size", "error": str(exc)})
        time.sleep(sleep_seconds)

    result: dict[str, pd.DataFrame] = {"_errors": pd.DataFrame(errors)}  # type: ignore[dict-item]
    for field, frames in buckets.items():
        if frames:
            result[field] = validate_observations(pd.concat(frames, ignore_index=True))
        else:
            result[field] = pd.DataFrame(columns=[
                "code", "observation_date", "available_at", "value",
                "source", "source_version", "retrieved_at",
            ])
    result["_source_version"] = version  # type: ignore[assignment]
    return result
