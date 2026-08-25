"""Free public sources for margin and daily ETF shares (no TuShare token).

Sources verified in-environment:
- Eastmoney ``RPTA_WEB_RZRQ_GGMX``: per-code daily ``RZYE`` / ``RZMRE`` history
- SSE ``fund_etf_scale_sse(date)``: Shanghai ETF daily share snapshot (份)
- SZSE ``fund_scale_daily_szse``: Shenzhen ETF daily shares in ≤6-month windows (份)

Absent securities stay missing (never zero-filled). Quarterly fund-scale
aggregates are not used.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd
import requests

from etf_rotation.non_ohlcv.schema import validate_observations
from etf_rotation.non_ohlcv.tushare_source import next_session_available_at

EM_MARGIN_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_MARGIN_REPORT = "RPTA_WEB_RZRQ_GGMX"
SOURCE_VERSION_PREFIX = "free"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "code", "observation_date", "available_at", "value",
        "source", "source_version", "retrieved_at",
    ])


def _to_obs(
    codes: pd.Series,
    dates: pd.Series,
    values: pd.Series,
    *,
    field: str,
    source: str,
    source_version: str,
    trading_calendar: pd.DatetimeIndex | None,
    retrieved_at: datetime,
) -> pd.DataFrame:
    frame = pd.DataFrame({
        "code": codes.astype(str).str.zfill(6),
        "observation_date": pd.to_datetime(dates),
        "value": pd.to_numeric(values, errors="coerce"),
        "source": source,
        "source_version": source_version,
        "retrieved_at": retrieved_at,
    })
    frame = frame.loc[frame["value"].notna()].copy()
    if frame.empty:
        return _empty()
    frame["available_at"] = next_session_available_at(frame["observation_date"], trading_calendar)
    frame["source"] = f"{source}/{field}"
    return validate_observations(frame)


def fetch_eastmoney_margin_code(
    code: str,
    *,
    source_version: str,
    trading_calendar: pd.DatetimeIndex | None = None,
    page_size: int = 500,
    sleep_seconds: float = 0.2,
    session: requests.Session | None = None,
) -> dict[str, pd.DataFrame]:
    """Download full Eastmoney margin history for one 6-digit code."""
    sess = session or requests.Session()
    retrieved = _now()
    rows: list[dict] = []
    page = 1
    total = None
    while True:
        params = {
            "reportName": EM_MARGIN_REPORT,
            "columns": "DATE,SCODE,SECNAME,RZYE,RZMRE",
            "filter": f'(SCODE="{str(code).zfill(6)}")',
            "pageNumber": page,
            "pageSize": page_size,
            "sortColumns": "DATE",
            "sortTypes": 1,
            "source": "WEB",
            "client": "WEB",
        }
        response = sess.get(EM_MARGIN_URL, params=params, timeout=45)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            raise RuntimeError(f"Eastmoney margin failed for {code}: {payload.get('message')}")
        result = payload.get("result") or {}
        if total is None:
            total = int(result.get("count") or 0)
        batch = result.get("data") or []
        if not batch:
            break
        rows.extend(batch)
        if total is not None and len(rows) >= total:
            break
        if len(batch) < page_size:
            break
        page += 1
        time.sleep(sleep_seconds)
    if not rows:
        return {"rzye": _empty(), "rzmre": _empty()}
    raw = pd.DataFrame(rows)
    return {
        "rzye": _to_obs(
            raw["SCODE"], raw["DATE"], raw["RZYE"],
            field="rzye", source="Eastmoney", source_version=source_version,
            trading_calendar=trading_calendar, retrieved_at=retrieved,
        ),
        "rzmre": _to_obs(
            raw["SCODE"], raw["DATE"], raw["RZMRE"],
            field="rzmre", source="Eastmoney", source_version=source_version,
            trading_calendar=trading_calendar, retrieved_at=retrieved,
        ),
    }


def fetch_sse_shares_for_dates(
    dates: list[pd.Timestamp] | pd.DatetimeIndex,
    *,
    codes: set[str],
    source_version: str,
    trading_calendar: pd.DatetimeIndex | None = None,
    sleep_seconds: float = 0.25,
    progress: Callable[[str], None] | None = None,
    checkpoint_path: Path | None = None,
) -> pd.DataFrame:
    """SSE daily ETF shares via AkShare ``fund_etf_scale_sse`` (单位: 份)."""
    import akshare as ak

    retrieved = _now()
    frames: list[pd.DataFrame] = []
    done_dates: set[str] = set()
    if checkpoint_path is not None and checkpoint_path.exists():
        prior = pd.read_parquet(checkpoint_path)
        if not prior.empty:
            frames.append(prior)
            done_dates = set(pd.to_datetime(prior["observation_date"]).dt.strftime("%Y%m%d"))
            if progress:
                progress(f"SSE shares resume: {len(done_dates)} dates already cached")
    wanted = {str(c).zfill(6) for c in codes}
    for index, stamp in enumerate(pd.to_datetime(dates), start=1):
        day = pd.Timestamp(stamp).strftime("%Y%m%d")
        if day in done_dates:
            continue
        if progress and index % 25 == 0:
            progress(f"SSE shares {index}/{len(dates)} {day}")
        try:
            raw = ak.fund_etf_scale_sse(date=day)
        except Exception as exc:  # noqa: BLE001 - keep going; gaps stay missing
            if progress and index % 100 == 0:
                progress(f"SSE shares skip {day}: {exc}")
            time.sleep(min(sleep_seconds, 0.15))
            continue
        if raw is None or raw.empty or "基金代码" not in getattr(raw, "columns", []):
            time.sleep(min(sleep_seconds, 0.1))
            continue
        subset = raw.loc[raw["基金代码"].astype(str).str.zfill(6).isin(wanted)].copy()
        if subset.empty:
            time.sleep(sleep_seconds)
            continue
        date_col = "统计日期" if "统计日期" in subset.columns else None
        obs_dates = (
            pd.to_datetime(subset[date_col]) if date_col else pd.Timestamp(stamp)
        )
        chunk = pd.DataFrame({
            "code": subset["基金代码"].astype(str).str.zfill(6),
            "observation_date": obs_dates,
            "value": pd.to_numeric(subset["基金份额"], errors="coerce"),
        })
        frames.append(chunk)
        done_dates.add(day)
        if checkpoint_path is not None and index % 50 == 0:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            pd.concat(frames, ignore_index=True).to_parquet(checkpoint_path, index=False)
        time.sleep(sleep_seconds)
    if not frames:
        return _empty()
    merged = pd.concat(frames, ignore_index=True)
    if checkpoint_path is not None:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        merged.to_parquet(checkpoint_path, index=False)
    return _to_obs(
        merged["code"], merged["observation_date"], merged["value"],
        field="total_share", source="SSE/fund_etf_scale_sse",
        source_version=source_version, trading_calendar=trading_calendar,
        retrieved_at=retrieved,
    )


def fetch_szse_shares_range(
    start_date: str,
    end_date: str,
    *,
    codes: set[str],
    source_version: str,
    trading_calendar: pd.DatetimeIndex | None = None,
    chunk_months: int = 6,
    sleep_seconds: float = 0.5,
    progress: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    """SZSE daily ETF shares via AkShare ``fund_scale_daily_szse`` (单位: 份)."""
    import akshare as ak

    retrieved = _now()
    wanted = {str(c).zfill(6) for c in codes}
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    frames: list[pd.DataFrame] = []
    cursor = start
    while cursor <= end:
        # API rejects windows longer than ~6 months.
        window_end = min(cursor + pd.DateOffset(months=chunk_months) - pd.Timedelta(days=1), end)
        s = cursor.strftime("%Y%m%d")
        e = window_end.strftime("%Y%m%d")
        if progress:
            progress(f"SZSE shares {s}->{e}")
        try:
            raw = ak.fund_scale_daily_szse(start_date=s, end_date=e, symbol="ETF")
        except Exception as exc:  # noqa: BLE001
            if progress:
                progress(f"SZSE shares skip {s}->{e}: {exc}")
            cursor = window_end + pd.Timedelta(days=1)
            time.sleep(sleep_seconds)
            continue
        if raw is not None and not raw.empty and "基金代码" in raw.columns:
            subset = raw.loc[raw["基金代码"].astype(str).str.zfill(6).isin(wanted)].copy()
            if not subset.empty:
                frames.append(pd.DataFrame({
                    "code": subset["基金代码"].astype(str).str.zfill(6),
                    "observation_date": pd.to_datetime(subset["日期"]),
                    "value": pd.to_numeric(subset["基金份额"], errors="coerce"),
                }))
        cursor = window_end + pd.Timedelta(days=1)
        time.sleep(sleep_seconds)
    if not frames:
        return _empty()
    merged = pd.concat(frames, ignore_index=True)
    return _to_obs(
        merged["code"], merged["observation_date"], merged["value"],
        field="total_share", source="SZSE/fund_scale_daily_szse",
        source_version=source_version, trading_calendar=trading_calendar,
        retrieved_at=retrieved,
    )


def download_free_universe_observations(
    codes: list[str],
    *,
    start_date: str,
    end_date: str,
    trading_calendar: pd.DatetimeIndex | None = None,
    sleep_seconds: float = 0.25,
    source_version: str | None = None,
    progress: Callable[[str], None] | None = None,
    include_sse_shares: bool = True,
    include_szse_shares: bool = True,
    include_margin: bool = True,
    sse_checkpoint: Path | None = None,
    sse_dates: list[pd.Timestamp] | pd.DatetimeIndex | None = None,
) -> dict[str, pd.DataFrame]:
    """Download free margin + daily share observations for the ETF universe."""
    version = source_version or datetime.now(timezone.utc).strftime(f"{SOURCE_VERSION_PREFIX}_%Y%m%dT%H%M%SZ")
    codes = [str(c).zfill(6) for c in codes]
    sh_codes = {c for c in codes if c.startswith(("5", "6", "9"))}
    sz_codes = {c for c in codes if c.startswith("1")}
    errors: list[dict[str, str]] = []
    rzye_parts: list[pd.DataFrame] = []
    rzmre_parts: list[pd.DataFrame] = []
    share_parts: list[pd.DataFrame] = []
    session = requests.Session()

    if include_margin:
        for code in codes:
            if progress:
                progress(f"Eastmoney margin {code}")
            try:
                margin = fetch_eastmoney_margin_code(
                    code,
                    source_version=version,
                    trading_calendar=trading_calendar,
                    sleep_seconds=sleep_seconds,
                    session=session,
                )
                if not margin["rzye"].empty:
                    rzye_parts.append(margin["rzye"])
                if not margin["rzmre"].empty:
                    rzmre_parts.append(margin["rzmre"])
            except Exception as exc:  # noqa: BLE001
                errors.append({"code": code, "field": "eastmoney_margin", "error": str(exc)})
            time.sleep(sleep_seconds)

    # Prefer SZSE bulk windows before the slower SSE day loop.
    if include_szse_shares and sz_codes:
        try:
            shares = fetch_szse_shares_range(
                start_date,
                end_date,
                codes=sz_codes,
                source_version=version,
                trading_calendar=trading_calendar,
                sleep_seconds=max(sleep_seconds, 0.4),
                progress=progress,
            )
            if not shares.empty:
                share_parts.append(shares)
        except Exception as exc:  # noqa: BLE001
            errors.append({"code": "SZSE", "field": "fund_scale_daily_szse", "error": str(exc)})

    if include_sse_shares and sh_codes:
        start_ts, end_ts = pd.Timestamp(start_date), pd.Timestamp(end_date)
        sse_floor = pd.Timestamp("2010-01-01")
        if sse_dates is None:
            calendar = trading_calendar
            if calendar is None:
                calendar = pd.date_range(start_date, end_date, freq="B")
            sse_dates = list(calendar)
        filtered = [
            d for d in pd.to_datetime(sse_dates)
            if max(start_ts, sse_floor) <= pd.Timestamp(d) <= end_ts
        ]
        if progress:
            progress(f"SSE shares days={len(filtered)} (floor {sse_floor.date()})")
        try:
            shares = fetch_sse_shares_for_dates(
                filtered,
                codes=sh_codes,
                source_version=version,
                trading_calendar=trading_calendar,
                sleep_seconds=sleep_seconds,
                progress=progress,
                checkpoint_path=sse_checkpoint,
            )
            if not shares.empty:
                share_parts.append(shares)
        except Exception as exc:  # noqa: BLE001
            errors.append({"code": "SSE", "field": "fund_etf_scale_sse", "error": str(exc)})

    def _cat(parts: list[pd.DataFrame]) -> pd.DataFrame:
        if not parts:
            return _empty()
        return validate_observations(pd.concat(parts, ignore_index=True))

    return {
        "rzye": _cat(rzye_parts),
        "rzmre": _cat(rzmre_parts),
        "total_share": _cat(share_parts),
        "_errors": pd.DataFrame(errors),
        "_source_version": version,
        "_source_label": (
            "Eastmoney margin + SSE/SZSE daily ETF shares (free; no TuShare)"
        ),
    }
