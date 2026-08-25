"""Validation gates for non-OHLCV production promotion."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from etf_rotation.non_ohlcv.compute import (
    margin_buy_ratio,
    margin_change,
    panel_from_observations,
    share_change,
)
from etf_rotation.non_ohlcv.schema import REQUIRED_COLUMNS, validate_observations

PRODUCTION_MISSING_RATIO = 0.05
FACTOR_NAMES = (
    "MARGIN_BUY_RATIO",
    "MARGIN_CHG_10D",
    "SHARE_CHG_5D",
    "SHARE_CHG_20D",
)


@dataclass
class FieldValidation:
    field: str
    rows: int
    codes: int
    date_min: str
    date_max: str
    missing_ratio_on_grid: float
    max_gap_days: float | None
    unit_ok: bool
    pit_ok: bool
    lookahead_violations: int
    notes: list[str] = field(default_factory=list)


@dataclass
class FactorValidation:
    factor: str
    missing_ratio: float
    missing_ratio_full_grid: float
    missing_ratio_eligible_grid: float
    codes: int
    date_min: str
    date_max: str
    pit_ok: bool
    production_eligible: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    source: str
    source_version: str
    field_results: list[FieldValidation]
    factor_results: list[FactorValidation]
    qmt_differences: list[str]
    unblock_blocked_by_data: bool
    status: str
    notes: list[str] = field(default_factory=list)

    @property
    def all_factors_production(self) -> bool:
        return bool(self.factor_results) and all(item.production_eligible for item in self.factor_results)


def expected_grid(prices: dict[str, pd.DataFrame], codes: list[str]) -> pd.DataFrame:
    """Code×date grid from cached OHLCV only; no invented bars."""
    rows = []
    for code in codes:
        frame = prices.get(code)
        if frame is None or frame.empty:
            continue
        for stamp in pd.to_datetime(frame["date"]):
            rows.append({"code": code, "date": pd.Timestamp(stamp).normalize()})
    if not rows:
        return pd.DataFrame(columns=["code", "date"])
    return pd.DataFrame(rows).drop_duplicates()


def _ohlcv_panels(
    prices: dict[str, pd.DataFrame], codes: list[str], dates: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.DataFrame]:
    close = pd.DataFrame(index=dates, columns=codes, dtype=float)
    volume = pd.DataFrame(index=dates, columns=codes, dtype=float)
    for code in codes:
        frame = prices.get(code)
        if frame is None or frame.empty:
            continue
        indexed = frame.set_index(pd.to_datetime(frame["date"]).dt.normalize())
        close[code] = indexed["close"].reindex(dates)
        volume[code] = indexed["volume"].reindex(dates)
    return close, volume


def _panel_to_long(panel: pd.DataFrame) -> pd.DataFrame:
    try:
        long = panel.stack(future_stack=True).rename("value").reset_index()
    except TypeError:
        long = panel.stack(dropna=False).rename("value").reset_index()
    long.columns = ["date", "code", "value"]
    long["date"] = pd.to_datetime(long["date"])
    long["code"] = long["code"].astype(str).str.zfill(6)
    return long


def validate_raw_field(
    observations: pd.DataFrame,
    *,
    field: str,
    grid: pd.DataFrame,
    trading_calendar: pd.DatetimeIndex,
) -> FieldValidation:
    notes: list[str] = []
    if observations is None or observations.empty:
        return FieldValidation(
            field=field, rows=0, codes=0, date_min="", date_max="",
            missing_ratio_on_grid=1.0, max_gap_days=None, unit_ok=False, pit_ok=False,
            lookahead_violations=0, notes=["empty observations; refusing production write"],
        )
    obs = validate_observations(observations)
    pit_ok = not (obs["available_at"] < obs["observation_date"]).any()
    # Lookahead relative to observation: available_at must be on/after observation_date
    # and signal use must enforce available_at <= signal_date (checked when building panels).
    lookahead_violations = int((obs["available_at"] < obs["observation_date"]).sum())

    panel = panel_from_observations(
        obs,
        pd.DatetimeIndex(sorted(grid["date"].unique())),
        sorted(grid["code"].unique()),
    )
    long = _panel_to_long(panel)
    merged = grid.merge(long, on=["code", "date"], how="left")
    missing_ratio = float(merged["value"].isna().mean()) if len(merged) else 1.0

    gaps = []
    for code, subset in obs.groupby("code"):
        stamps = pd.DatetimeIndex(subset["observation_date"].sort_values().unique())
        if len(stamps) < 2:
            continue
        # Gaps measured on trading calendar positions.
        positions = trading_calendar.searchsorted(stamps.normalize())
        gaps.append(float(np.diff(positions).max() - 1) if len(positions) > 1 else 0.0)
    max_gap = float(max(gaps)) if gaps else None

    values = obs["value"]
    if field in {"rzye", "rzmre"}:
        unit_ok = bool((values.dropna() >= 0).all()) and bool((values.dropna() < 1e16).all())
        if not unit_ok:
            notes.append("rzye/rzmre expected non-negative CNY amounts")
    elif field == "total_share":
        # SSE/SZSE free sources use 份; TuShare etf_share_size uses 万份.
        # Relative SHARE_CHG is unit-invariant when a single source is consistent.
        unit_ok = bool((values.dropna() > 0).all()) and bool((values.dropna() < 1e14).all())
        notes.append("total_share units: SSE/SZSE=份, TuShare=万份; SHARE_CHG is relative")
        if not unit_ok:
            notes.append("total_share failed positivity/magnitude check")
    else:
        unit_ok = bool(values.notna().any())

    if missing_ratio >= PRODUCTION_MISSING_RATIO:
        notes.append(f"missing_ratio_on_grid={missing_ratio:.4f} >= {PRODUCTION_MISSING_RATIO}")

    return FieldValidation(
        field=field,
        rows=len(obs),
        codes=int(obs["code"].nunique()),
        date_min=str(obs["observation_date"].min().date()),
        date_max=str(obs["observation_date"].max().date()),
        missing_ratio_on_grid=missing_ratio,
        max_gap_days=max_gap,
        unit_ok=unit_ok,
        pit_ok=pit_ok and lookahead_violations == 0,
        lookahead_violations=lookahead_violations,
        notes=notes,
    )


def build_factor_frames(
    raw: dict[str, pd.DataFrame],
    prices: dict[str, pd.DataFrame],
    codes: list[str],
) -> dict[str, pd.DataFrame]:
    """Compute long-format factor frames with PIT panels; NaN preserved."""
    grid = expected_grid(prices, codes)
    if grid.empty:
        return {}
    dates = pd.DatetimeIndex(sorted(grid["date"].unique()))
    close, volume = _ohlcv_panels(prices, codes, dates)
    rzye = panel_from_observations(raw.get("rzye", pd.DataFrame(columns=REQUIRED_COLUMNS)), dates, codes)
    rzmre = panel_from_observations(raw.get("rzmre", pd.DataFrame(columns=REQUIRED_COLUMNS)), dates, codes)
    share = panel_from_observations(
        raw.get("total_share", pd.DataFrame(columns=REQUIRED_COLUMNS)), dates, codes
    )
    factors = {
        "MARGIN_BUY_RATIO": margin_buy_ratio(rzmre, close, volume),
        "MARGIN_CHG_10D": margin_change(rzye, 10),
        "SHARE_CHG_5D": share_change(share, 5),
        "SHARE_CHG_20D": share_change(share, 20),
    }
    # Attach available_at as the signal date itself after PIT asof (already enforced).
    out: dict[str, pd.DataFrame] = {}
    for name, panel in factors.items():
        long = _panel_to_long(panel)
        long = grid.merge(long, on=["code", "date"], how="left")
        long["observation_date"] = long["date"]
        long["available_at"] = long["date"]  # values already PIT-filtered to this signal date
        long["source"] = "TuShare/derived"
        long["source_version"] = "derived_from_validated_raw"
        long["retrieved_at"] = pd.Timestamp.now(tz="UTC")
        out[name] = long
    return out


def _eligible_mask_for_share_factor(frame: pd.DataFrame, warmup: int) -> pd.Series:
    """Exclude pre-listing and the first `warmup` sessions after first observation."""
    dates = pd.to_datetime(frame["date"])
    eligible = pd.Series(False, index=frame.index)
    for _, subset in frame.groupby("code"):
        code_idx = subset.index
        code_dates = pd.to_datetime(subset["date"]).sort_values()
        listing = code_dates.min()
        observed = subset.loc[subset["value"].notna(), "date"]
        if observed.empty:
            continue
        first_obs = pd.to_datetime(observed).min()
        ordered = [
            stamp for stamp in sorted(pd.DatetimeIndex(code_dates).unique())
            if stamp >= first_obs
        ]
        ok = set(ordered[warmup:]) if len(ordered) > warmup else set()
        eligible.loc[code_idx] = dates.loc[code_idx].isin(ok) & dates.loc[code_idx].ge(listing)
    return eligible


def validate_factors(factor_frames: dict[str, pd.DataFrame]) -> list[FactorValidation]:
    results = []
    for name in FACTOR_NAMES:
        frame = factor_frames.get(name)
        if frame is None or frame.empty:
            results.append(FactorValidation(
                factor=name, missing_ratio=1.0, missing_ratio_full_grid=1.0,
                missing_ratio_eligible_grid=1.0, codes=0, date_min="", date_max="",
                pit_ok=False, production_eligible=False,
                notes=["factor frame empty"],
            ))
            continue
        missing_full = float(frame["value"].isna().mean())
        pit_ok = bool((frame["available_at"] <= frame["date"]).all())
        notes: list[str] = []
        if name.startswith("SHARE_CHG"):
            warmup = 5 if name.endswith("5D") else 20
            eligible = _eligible_mask_for_share_factor(frame, warmup)
            missing_eligible = (
                float(frame.loc[eligible, "value"].isna().mean()) if eligible.any() else 1.0
            )
            gate_ratio = missing_eligible
            notes.append(
                f"full_grid_missing_ratio={missing_full:.4f}; "
                f"eligible_grid_missing_ratio={missing_eligible:.4f} "
                f"(excludes pre-listing + {warmup}D warmup)"
            )
        else:
            # MARGIN_*: never shrink denominator for non-marginable names.
            missing_eligible = missing_full
            gate_ratio = missing_full
            notes.append(
                f"full_grid_missing_ratio={missing_full:.4f}; "
                "eligible_grid equals full grid (no structural exclusion for promotion)"
            )
        eligible_flag = gate_ratio < PRODUCTION_MISSING_RATIO and pit_ok
        if gate_ratio >= PRODUCTION_MISSING_RATIO:
            notes.append(f"gate_missing_ratio={gate_ratio:.4f} >= {PRODUCTION_MISSING_RATIO}")
        if not pit_ok:
            notes.append("available_at > signal_date for some rows")
        results.append(FactorValidation(
            factor=name,
            missing_ratio=missing_full,
            missing_ratio_full_grid=missing_full,
            missing_ratio_eligible_grid=missing_eligible,
            codes=int(frame.loc[frame["value"].notna(), "code"].nunique()),
            date_min=str(pd.to_datetime(frame["date"]).min().date()),
            date_max=str(pd.to_datetime(frame["date"]).max().date()),
            pit_ok=pit_ok,
            production_eligible=eligible_flag,
            notes=notes,
        ))
    return results


def run_validation(
    raw: dict[str, pd.DataFrame],
    prices: dict[str, pd.DataFrame],
    codes: list[str],
    *,
    source_version: str,
    source_label: str | None = None,
) -> tuple[ValidationReport, dict[str, pd.DataFrame]]:
    grid = expected_grid(prices, codes)
    calendar = pd.DatetimeIndex(sorted(grid["date"].unique())) if not grid.empty else pd.DatetimeIndex([])
    field_results = [
        validate_raw_field(raw.get(field, pd.DataFrame()), field=field, grid=grid, trading_calendar=calendar)
        for field in ("rzye", "rzmre", "total_share")
    ]
    factor_frames = build_factor_frames(raw, prices, codes)
    factor_results = validate_factors(factor_frames)
    eligible_names = [item.factor for item in factor_results if item.production_eligible]
    unblock = bool(factor_results) and all(item.production_eligible for item in factor_results)
    qmt_differences = [
        "QMT local bridge timestamps and revision handling are unpublished; next-session 08:30 is a conservative public proxy.",
        "Exchange/Eastmoney share units are 份; TuShare etf_share_size uses 万份; relative SHARE_CHG is unit-invariant if consistent.",
        "margin coverage is exchange margin-target history; ETFs absent from a day remain missing (not zero).",
        "Adjustment and overseas QDII share timing differ; A_SHARE_ONLY still excludes QDII from trading.",
    ]
    notes = [
        f"Per-factor production_eligible: {eligible_names or 'none'}. "
        "Staging remains readable in research mode even when not all factors promote."
    ]
    if not unblock:
        notes.append(
            "Overall BLOCKED_BY_DATA for full v8 seal; individual eligible factors may still promote."
        )
    else:
        notes.append("All four factors satisfy gate missing_ratio < 5% and PIT.")
    report = ValidationReport(
        source=source_label or "unknown",
        source_version=source_version,
        field_results=field_results,
        factor_results=factor_results,
        qmt_differences=qmt_differences,
        unblock_blocked_by_data=unblock,
        status="production" if unblock else "BLOCKED_BY_DATA",
        notes=notes,
    )
    return report, factor_frames


def render_validation_markdown(report: ValidationReport, path: Path) -> None:
    field_rows = pd.DataFrame([
        {
            "field": item.field,
            "rows": item.rows,
            "codes": item.codes,
            "date_min": item.date_min,
            "date_max": item.date_max,
            "missing_ratio_on_grid": round(item.missing_ratio_on_grid, 4),
            "max_gap_sessions": item.max_gap_days,
            "unit_ok": item.unit_ok,
            "pit_ok": item.pit_ok,
            "lookahead_violations": item.lookahead_violations,
            "notes": "; ".join(item.notes),
        }
        for item in report.field_results
    ])
    factor_rows = pd.DataFrame([
        {
            "factor": item.factor,
            "missing_ratio_full_grid": round(item.missing_ratio_full_grid, 4),
            "missing_ratio_eligible_grid": round(item.missing_ratio_eligible_grid, 4),
            "codes_with_values": item.codes,
            "date_min": item.date_min,
            "date_max": item.date_max,
            "pit_ok": item.pit_ok,
            "production_eligible": item.production_eligible,
            "notes": "; ".join(item.notes),
        }
        for item in report.factor_results
    ])
    coverage_codes = max((item.codes for item in report.field_results), default=0)
    date_mins = [item.date_min for item in report.field_results if item.date_min]
    date_maxs = [item.date_max for item in report.field_results if item.date_max]
    text = [
        "# Non-OHLCV validation",
        "",
        f"- Data source: **{report.source}**",
        f"- Source version: `{report.source_version}`",
        f"- Coverage date range: `{min(date_mins) if date_mins else 'n/a'}` → `{max(date_maxs) if date_maxs else 'n/a'}`",
        f"- Max ETF codes with raw values (any field): **{coverage_codes}**",
        f"- Status: **{report.status}**",
        f"- Unblock BLOCKED_BY_DATA: **{'yes' if report.unblock_blocked_by_data else 'no'}**",
        "",
        "## Raw field checks",
        "",
        field_rows.to_markdown(index=False) if not field_rows.empty else "_no raw fields_",
        "",
        "## Factor production gate (`missing_ratio < 0.05` and `available_at <= signal_date`)",
        "",
        factor_rows.to_markdown(index=False) if not factor_rows.empty else "_no factors_",
        "",
        "## Possible differences versus QMT",
        "",
        *[f"- {line}" for line in report.qmt_differences],
        "",
        "## Notes",
        "",
        *[f"- {line}" for line in report.notes],
        "",
        "Empty downloads never write production parquet. Missing inputs stay NaN (never zero-filled). "
        "Quarterly fund-scale pages are not used.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(text) + "\n", encoding="utf-8")
