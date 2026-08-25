"""Fetch, version, validate, and optionally promote non-OHLCV caches."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from etf_rotation.config import RotationConfig
from etf_rotation.data import cached_prices, universe_definition
from etf_rotation.non_ohlcv.free_source import download_free_universe_observations
from etf_rotation.non_ohlcv.schema import write_observations
from etf_rotation.non_ohlcv.tushare_source import (
    TuShareTokenError,
    download_universe_observations,
    resolve_tushare_token,
)
from etf_rotation.non_ohlcv.validate import (
    FACTOR_NAMES,
    render_validation_markdown,
    run_validation,
)


def non_ohlcv_root(config: RotationConfig) -> Path:
    return config.cache_dir / "non_ohlcv"


def production_manifest_path(config: RotationConfig) -> Path:
    return non_ohlcv_root(config) / "production_manifest.json"


def _yyyyymmdd(value: pd.Timestamp | str) -> str:
    return pd.Timestamp(value).strftime("%Y%m%d")


def _date_span(prices: dict[str, pd.DataFrame]) -> tuple[str, str]:
    firsts, lasts = [], []
    for frame in prices.values():
        if frame is None or frame.empty:
            continue
        dates = pd.to_datetime(frame["date"])
        firsts.append(dates.min())
        lasts.append(dates.max())
    if not firsts:
        raise RuntimeError("no cached OHLCV prices; run `etf-rotation fetch --full` first")
    return _yyyyymmdd(min(firsts)), _yyyyymmdd(max(lasts))


def _trading_calendar(prices: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    stamps = []
    for frame in prices.values():
        if frame is None or frame.empty:
            continue
        stamps.extend(pd.to_datetime(frame["date"]).tolist())
    return pd.DatetimeIndex(pd.to_datetime(stamps)).normalize().unique().sort_values()


def _refuse_overwrite_production(config: RotationConfig) -> None:
    manifest = production_manifest_path(config)
    if not manifest.exists():
        return
    data = json.loads(manifest.read_text(encoding="utf-8"))
    # Allow additive per-factor promotion; only refuse clobbering a full sealed set
    # when caller would rewrite all raw without an explicit new version directory.
    if data.get("status") == "production" and set(data.get("factors") or []) == set(FACTOR_NAMES):
        # Still allow fetch: raw versions are versioned; promotion merges factor_tiers.
        return


def _write_raw_version(
    config: RotationConfig,
    raw: dict[str, pd.DataFrame],
    source_version: str,
    *,
    source_label: str,
) -> Path:
    root = non_ohlcv_root(config) / "raw" / source_version
    root.mkdir(parents=True, exist_ok=True)
    wrote = False
    for field in ("rzye", "rzmre", "total_share"):
        frame = raw.get(field)
        if frame is None or frame.empty:
            continue
        write_observations(frame, root / f"{field}.parquet")
        wrote = True
    errors = raw.get("_errors")
    if isinstance(errors, pd.DataFrame) and not errors.empty:
        errors.to_csv(root / "download_errors.csv", index=False)
    if not wrote:
        for path in root.glob("*"):
            path.unlink()
        root.rmdir()
        raise RuntimeError(
            "No non-OHLCV rows returned; refusing to write empty parquet files."
        )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "source": source_label,
                "source_version": source_version,
                "fields": [
                    f for f in ("rzye", "rzmre", "total_share")
                    if (root / f"{f}.parquet").exists()
                ],
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return root


def _write_staging_factors(
    config: RotationConfig, factors: dict[str, pd.DataFrame], version: str
) -> Path:
    root = non_ohlcv_root(config) / "staging" / version
    root.mkdir(parents=True, exist_ok=True)
    for name, frame in factors.items():
        if frame is None or frame.empty:
            continue
        frame.to_parquet(root / f"{name}.parquet", index=False)
    return root


def _promote_production(
    config: RotationConfig,
    factors: dict[str, pd.DataFrame],
    *,
    source_version: str,
    source_label: str,
    validation_path: Path,
    factor_results,
) -> list[str]:
    """Promote each production_eligible factor independently; never zero-fill."""
    root = non_ohlcv_root(config)
    root.mkdir(parents=True, exist_ok=True)
    promoted: list[str] = []
    tiers: dict[str, str] = {}
    for item in factor_results:
        name = item.factor
        tiers[name] = "unavailable"
        frame = factors.get(name)
        if frame is None or frame.empty:
            continue
        if not item.production_eligible:
            # Keep staging only; do not write production path.
            continue
        # Gate already checked eligible ratio; still refuse NaN-invented zeros.
        frame.to_parquet(root / f"{name}.parquet", index=False)
        promoted.append(name)
        tiers[name] = "production"
    # Preserve previously promoted factors not in this run if files remain.
    existing = production_manifest_path(config)
    prior_tiers: dict[str, str] = {}
    if existing.exists():
        prior = json.loads(existing.read_text(encoding="utf-8"))
        prior_tiers = dict(prior.get("factor_tiers") or {})
    for name in FACTOR_NAMES:
        if tiers.get(name) == "production":
            continue
        if prior_tiers.get(name) == "production" and (root / f"{name}.parquet").exists():
            tiers[name] = "production"
            if name not in promoted:
                promoted.append(name)
    production_manifest_path(config).write_text(
        json.dumps(
            {
                "status": "production" if len(promoted) == len(FACTOR_NAMES) else "partial_production",
                "source": source_label,
                "source_version": source_version,
                "validated_at": datetime.now(timezone.utc).isoformat(),
                "validation_report": str(validation_path),
                "factors": promoted,
                "factor_tiers": tiers,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return promoted


def _resolve_source(source: str, token: str | None) -> str:
    choice = (source or "auto").lower()
    if choice not in {"auto", "free", "tushare"}:
        raise ValueError("source must be auto|free|tushare")
    if choice == "auto":
        has_token = bool((token or os.environ.get("TUSHARE_TOKEN") or "").strip())
        return "tushare" if has_token else "free"
    return choice


def fetch_non_ohlcv(
    config: RotationConfig,
    *,
    full: bool,
    sleep_seconds: float = 0.35,
    token: str | None = None,
    source: str = "auto",
) -> dict[str, object]:
    """Download non-OHLCV fields, validate, and promote only if gates pass."""
    if not full:
        raise RuntimeError("fetch-non-ohlcv requires --full (refuses partial silent caches)")
    resolved = _resolve_source(source, token)
    if resolved == "tushare":
        resolve_tushare_token(token)
    _refuse_overwrite_production(config)

    prices = cached_prices(config)
    if not prices:
        raise RuntimeError("no cached OHLCV prices; run `etf-rotation fetch --full` first")
    definition = universe_definition(config)
    codes = definition["code"].astype(str).str.zfill(6).tolist()
    start_date, end_date = _date_span(prices)
    calendar = _trading_calendar(prices)
    progress = lambda message: print(message, flush=True)

    if resolved == "free":
        version = datetime.now(timezone.utc).strftime("free_%Y%m%dT%H%M%SZ")
        checkpoint = non_ohlcv_root(config) / "checkpoints" / version / "sse_shares_raw.parquet"
        sh_codes = [c for c in codes if c.startswith(("5", "6", "9"))]
        sse_dates = []
        for code in sh_codes:
            frame = prices.get(code)
            if frame is None or frame.empty:
                continue
            sse_dates.extend(pd.to_datetime(frame["date"]).tolist())
        sse_dates = sorted(set(pd.to_datetime(sse_dates).normalize()))
        raw = download_free_universe_observations(
            codes,
            start_date=start_date,
            end_date=end_date,
            trading_calendar=calendar,
            sleep_seconds=sleep_seconds,
            source_version=version,
            progress=progress,
            sse_checkpoint=checkpoint,
            sse_dates=sse_dates,
        )
        empty_msg = (
            "Free sources returned no non-OHLCV rows; refusing empty parquet. "
            "Check Eastmoney / SSE / SZSE connectivity."
        )
    else:
        raw = download_universe_observations(
            codes,
            start_date=start_date,
            end_date=end_date,
            token=token,
            trading_calendar=calendar,
            sleep_seconds=sleep_seconds,
            progress=progress,
        )
        empty_msg = (
            "TuShare returned no non-OHLCV rows; refusing empty parquet. "
            "Check token points for margin_detail (>=2000) and etf_share_size (>=8000)."
        )

    source_version = str(raw.get("_source_version"))
    source_label = str(raw.get("_source_label") or resolved)
    field_raw = {key: value for key, value in raw.items() if not str(key).startswith("_")}
    if all(getattr(frame, "empty", True) for frame in field_raw.values()):
        raise RuntimeError(empty_msg)

    raw_dir = _write_raw_version(
        config, raw, source_version, source_label=source_label
    )
    report, factor_frames = run_validation(
        field_raw,
        prices,
        codes,
        source_version=source_version,
        source_label=source_label,
    )
    staging_dir = _write_staging_factors(config, factor_frames, source_version)
    validation_path = config.reports_dir / "non_ohlcv_validation.md"
    render_validation_markdown(report, validation_path)

    promoted = False
    promoted_factors: list[str] = []
    eligible_any = any(item.production_eligible for item in report.factor_results)
    if eligible_any:
        promoted_factors = _promote_production(
            config,
            factor_frames,
            source_version=source_version,
            source_label=source_label,
            validation_path=validation_path,
            factor_results=report.factor_results,
        )
        promoted = bool(promoted_factors)

    return {
        "source": resolved,
        "source_version": source_version,
        "raw_dir": raw_dir,
        "staging_dir": staging_dir,
        "validation_path": validation_path,
        "status": report.status,
        "promoted": promoted,
        "promoted_factors": promoted_factors,
        "errors": raw.get("_errors"),
    }
