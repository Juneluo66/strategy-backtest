"""OHLCV factor panel, non-OHLCV PIT merge, and mode-aware cross-sectional scores."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from etf_rotation.config import RotationConfig
from etf_rotation.non_ohlcv.loader import (
    NON_OHLCV_FACTORS,
    TIER_PRODUCTION,
    TIER_RESEARCH_STAGING,
    TIER_UNAVAILABLE,
    FactorSource,
    load_non_ohlcv_sources,
    merge_factor_into_panel,
)

OHLCV_FACTORS = {"MOM_20D", "SLOPE_20D", "ADX_14D", "BREAKOUT_20D", "PRICE_POSITION_120D"}
MARGIN_FACTORS = {"MARGIN_BUY_RATIO", "MARGIN_CHG_10D"}
SHARE_FACTORS = {"SHARE_CHG_5D", "SHARE_CHG_20D"}
WARMUP_BARS = {
    "SHARE_CHG_5D": 5,
    "SHARE_CHG_20D": 20,
    "MARGIN_CHG_10D": 10,
    "MARGIN_BUY_RATIO": 0,
}
RUN_MODES = ("strict", "research", "baseline")


class FactorAvailabilityError(RuntimeError):
    """Raised when declared factors cannot be used under the selected run mode."""


@dataclass
class FactorAudit:
    run_mode: str
    reproduction_status: str
    declared_factors: list[str]
    actual_factors: list[str]
    factor_tiers: dict[str, str]
    daily_coverage: pd.DataFrame
    excluded_etf_count_by_date: pd.Series
    etf_participation_ratio: pd.Series
    implicit_margin_screen: bool
    missing_reason_counts: dict[str, int]
    notes: list[str] = field(default_factory=list)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "run_mode": self.run_mode,
            "reproduction_status": self.reproduction_status,
            "declared_factors": self.declared_factors,
            "actual_factors": self.actual_factors,
            "factor_tiers": self.factor_tiers,
            "daily_coverage_summary": {
                "dates": int(len(self.daily_coverage)),
                "mean_complete_score_ratio": (
                    float(self.daily_coverage["complete_score_ratio"].mean())
                    if not self.daily_coverage.empty else None
                ),
                "mean_excluded_etf_count": (
                    float(self.daily_coverage["excluded_etf_count"].mean())
                    if not self.daily_coverage.empty else None
                ),
            },
            "coverage_by_factor_mean": {
                col.replace("coverage_", ""): float(self.daily_coverage[col].mean())
                for col in self.daily_coverage.columns
                if col.startswith("coverage_")
            } if not self.daily_coverage.empty else {},
            "etf_participation_ratio": {
                str(k): float(v) for k, v in self.etf_participation_ratio.items()
            },
            "implicit_margin_screen": self.implicit_margin_screen,
            "missing_reason_counts": self.missing_reason_counts,
            "notes": self.notes,
        }


def _adx(frame: pd.DataFrame, window: int = 14) -> pd.Series:
    high, low, close = frame["high"], frame["low"], frame["close"]
    up, down = high.diff(), -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1
    ).max(axis=1)
    atr = tr.rolling(window).mean()
    plus_di = 100 * plus_dm.rolling(window).mean() / atr
    minus_di = 100 * minus_dm.rolling(window).mean() / atr
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).replace(
        [np.inf, -np.inf], np.nan
    )
    return dx.rolling(window).mean()


def ohlcv_factor_panel(prices: dict[str, pd.DataFrame]) -> pd.DataFrame:
    parts = []
    for source in prices.values():
        frame = source.sort_values("date").copy()
        close = frame["close"]
        frame["MOM_20D"] = close.pct_change(20)
        frame["SLOPE_20D"] = close.pct_change().rolling(20).mean()
        frame["ADX_14D"] = _adx(frame)
        frame["BREAKOUT_20D"] = close / close.rolling(20).max().shift(1) - 1
        rolling_low, rolling_high = close.rolling(120).min(), close.rolling(120).max()
        frame["PRICE_POSITION_120D"] = (close - rolling_low) / (rolling_high - rolling_low)
        parts.append(frame[["date", "code", "open", "close", "amount", *sorted(OHLCV_FACTORS)]])
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    out["code"] = out["code"].astype(str).str.zfill(6)
    return out


def factor_panel(
    prices: dict[str, pd.DataFrame],
    config: RotationConfig | None = None,
    *,
    sources: dict[str, FactorSource] | None = None,
) -> pd.DataFrame:
    """OHLCV panel plus PIT-merged non-OHLCV factors. NaNs preserved."""
    panel = ohlcv_factor_panel(prices)
    if config is None and sources is None:
        return panel
    resolved = sources if sources is not None else load_non_ohlcv_sources(config)  # type: ignore[arg-type]
    for factor in NON_OHLCV_FACTORS:
        source = resolved.get(factor) or FactorSource(factor, TIER_UNAVAILABLE, None, None)
        panel = merge_factor_into_panel(panel, source)
        panel[f"_tier_{factor}"] = source.tier
    return panel


MARGIN_ABSENCE_KINDS = (
    "request_failed",
    "source_no_record",
    "not_margin_eligible",
    "symbol_mapping_failure",
    "unknown",
)


def classify_missing_reasons(
    panel: pd.DataFrame,
    factor: str,
    *,
    listing_dates: dict[str, pd.Timestamp],
    raw_first_obs: dict[str, pd.Timestamp] | None = None,
    download_failures: set[str] | None = None,
    margin_absence_kinds: dict[str, str] | None = None,
) -> pd.Series:
    """Classify NaN cells with explicit absence kinds (no blanket download_failure).

    Margin-code absences use one of:
    request_failed / source_no_record / not_margin_eligible /
    symbol_mapping_failure / unknown.
    Legacy ``download_failures`` sets map to ``unknown`` unless overridden.
    """
    kinds = dict(margin_absence_kinds or {})
    for code in download_failures or set():
        kinds.setdefault(str(code).zfill(6), "unknown")
    for code, kind in list(kinds.items()):
        if kind not in MARGIN_ABSENCE_KINDS:
            raise ValueError(f"invalid margin absence kind for {code}: {kind}")
    raw_first_obs = raw_first_obs or {}
    warmup = WARMUP_BARS.get(factor, 0)
    values = panel[factor] if factor in panel.columns else pd.Series(np.nan, index=panel.index)
    reasons = pd.Series("observed", index=panel.index, dtype=object)
    missing = values.isna()
    dates = pd.to_datetime(panel["date"])
    codes = panel["code"].astype(str)

    # Precompute per-code ordered dates after first observation for warmup checks.
    warmup_ok_index: dict[str, set[pd.Timestamp]] = {}
    for code, first in raw_first_obs.items():
        code_dates = dates.loc[codes.eq(code) & dates.ge(pd.Timestamp(first).normalize())]
        ordered = sorted(pd.DatetimeIndex(code_dates).unique())
        warmup_ok_index[code] = set(ordered[warmup:]) if len(ordered) > warmup else set()

    for idx in panel.index[missing]:
        code = codes.loc[idx]
        date = pd.Timestamp(dates.loc[idx]).normalize()
        listing = listing_dates.get(code)
        if listing is not None and date < pd.Timestamp(listing).normalize():
            reasons.loc[idx] = "pre_listing"
            continue
        if code in kinds and factor in MARGIN_FACTORS:
            reasons.loc[idx] = kinds[code]
            continue
        first = raw_first_obs.get(code)
        if first is None:
            reasons.loc[idx] = (
                "structurally_not_applicable" if factor in MARGIN_FACTORS else "source_missing"
            )
            continue
        first_ts = pd.Timestamp(first).normalize()
        if date < first_ts:
            reasons.loc[idx] = "pit_unavailable"
            continue
        if warmup > 0 and date not in warmup_ok_index.get(code, set()):
            reasons.loc[idx] = "rolling_warmup"
            continue
        reasons.loc[idx] = (
            "structurally_not_applicable" if factor in MARGIN_FACTORS else "source_missing"
        )
    reasons.loc[~missing] = "observed"
    return reasons


def _resolve_usable_factors(
    declared: list[str],
    panel: pd.DataFrame,
    *,
    run_mode: str,
    sources: dict[str, FactorSource],
) -> tuple[list[str], dict[str, str], list[str], str]:
    if run_mode not in RUN_MODES:
        raise ValueError(f"run_mode must be one of {RUN_MODES}")

    tiers: dict[str, str] = {}
    notes: list[str] = []
    for factor in declared:
        if factor in OHLCV_FACTORS:
            present = factor in panel.columns and not panel[factor].isna().all()
            tiers[factor] = TIER_PRODUCTION if present else TIER_UNAVAILABLE
        elif factor in NON_OHLCV_FACTORS:
            source = sources.get(factor)
            if source is not None:
                tiers[factor] = source.tier
            elif factor in panel.columns and not panel[factor].isna().all():
                # Panel already carries values (e.g. tests injected columns).
                tier_col = f"_tier_{factor}"
                tiers[factor] = (
                    str(panel[tier_col].dropna().iloc[0])
                    if tier_col in panel.columns and panel[tier_col].notna().any()
                    else TIER_RESEARCH_STAGING
                )
            else:
                tiers[factor] = TIER_UNAVAILABLE
        else:
            tiers[factor] = TIER_UNAVAILABLE if factor not in panel.columns else TIER_PRODUCTION

    non_ohlcv_declared = [f for f in declared if f in NON_OHLCV_FACTORS]

    if run_mode == "baseline":
        if non_ohlcv_declared:
            raise FactorAvailabilityError(
                "baseline mode refuses non-OHLCV declarations "
                f"{non_ohlcv_declared}; use research/strict or an OHLCV-only variant"
            )
        actual = [f for f in declared if f in OHLCV_FACTORS and f in panel.columns]
        if list(actual) != list(declared):
            raise FactorAvailabilityError(
                f"baseline declared {declared} but usable OHLCV factors are {actual}"
            )
        return actual, tiers, notes, "BASELINE_OHLCV"

    unavailable = [
        f for f in declared
        if f not in panel.columns or panel[f].isna().all() or tiers.get(f) == TIER_UNAVAILABLE
    ]
    if unavailable:
        raise FactorAvailabilityError(
            f"declared factors unavailable (no silent drop): {unavailable}; tiers={tiers}"
        )

    if run_mode == "strict":
        bad = [f for f in non_ohlcv_declared if tiers.get(f) != TIER_PRODUCTION]
        if bad:
            raise FactorAvailabilityError(
                f"strict mode requires production tier for {bad}; "
                f"got {{{', '.join(f'{k}:{tiers[k]}' for k in bad)}}}"
            )
        status = "PRODUCTION_FACTORS" if non_ohlcv_declared else "BASELINE_OHLCV"
        return list(declared), tiers, notes, status

    staging_used = [f for f in non_ohlcv_declared if tiers.get(f) == TIER_RESEARCH_STAGING]
    if staging_used:
        notes.append(f"using research_staging for {staging_used}")
        status = "PARTIAL_REPRODUCTION"
    else:
        status = "PRODUCTION_FACTORS" if non_ohlcv_declared else "BASELINE_OHLCV"
    return list(declared), tiers, notes, status


def cross_sectional_scores(
    panel: pd.DataFrame,
    factors: list[str],
    signs: list[float] | None = None,
    icirs: list[float] | None = None,
    *,
    run_mode: str = "research",
    sources: dict[str, FactorSource] | None = None,
    listing_dates: dict[str, pd.Timestamp] | None = None,
    raw_first_obs: dict[str, dict[str, pd.Timestamp]] | None = None,
    download_failures: set[str] | None = None,
    margin_absence_kinds: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, FactorAudit]:
    """Mode-aware scoring. Never silently drops declared factors; never zero-fills."""
    sources = sources or {}
    actual, tiers, notes, status = _resolve_usable_factors(
        factors, panel, run_mode=run_mode, sources=sources
    )
    signs = signs or [1.0] * len(factors)
    icirs = icirs or [1.0] * len(factors)
    lookup = {
        factor: (float(sign), abs(float(icir)))
        for factor, sign, icir in zip(factors, signs, icirs)
    }
    out = panel.copy()
    score = pd.Series(0.0, index=out.index)
    complete = pd.Series(True, index=out.index)
    weight_sum = 0.0
    for factor in actual:
        sign, weight = lookup[factor]

        def standardize(values: pd.Series) -> pd.Series:
            clipped = values.clip(values.quantile(0.025), values.quantile(0.975))
            std = clipped.std(ddof=0)
            return (clipped - clipped.mean()) / std if std and np.isfinite(std) else clipped * np.nan

        z = out.groupby("date", group_keys=False)[factor].apply(standardize)
        out[f"z_{factor}"] = z
        score += sign * weight * z
        complete &= z.notna()
        weight_sum += weight
    out["score"] = (score / weight_sum).where(complete) if weight_sum else np.nan
    out["available_factor_count"] = len(actual)
    out["requested_factor_count"] = len(factors)
    out["is_partial_factor_set"] = status == "PARTIAL_REPRODUCTION"
    out["run_mode"] = run_mode
    out["reproduction_status"] = status
    out["rank01"] = out.groupby("date")["score"].rank(pct=True, method="average")

    cov_rows = []
    for date, group in out.groupby("date"):
        row: dict[str, Any] = {"date": date, "n_etf": len(group)}
        for factor in actual:
            row[f"coverage_{factor}"] = float(group[factor].notna().mean())
        row["complete_score_ratio"] = float(group["score"].notna().mean())
        row["excluded_etf_count"] = int(group["score"].isna().sum())
        cov_rows.append(row)
    daily_coverage = pd.DataFrame(cov_rows).sort_values("date") if cov_rows else pd.DataFrame()
    excluded = (
        daily_coverage.set_index("date")["excluded_etf_count"]
        if not daily_coverage.empty
        else pd.Series(dtype=int)
    )
    participation = out.groupby("code")["score"].apply(lambda s: float(s.notna().mean()))

    margin_declared = [f for f in actual if f in MARGIN_FACTORS]
    implicit_margin = False
    if margin_declared:
        margin_missing = out[margin_declared].isna().all(axis=1)
        excluded_mask = out["score"].isna()
        if excluded_mask.any():
            overlap = float((excluded_mask & margin_missing).sum() / excluded_mask.sum())
            implicit_margin = overlap >= 0.5
            if implicit_margin:
                notes.append(
                    f"implicit_margin_screen=true (overlap={overlap:.2f} of excluded rows "
                    "lack all declared MARGIN_* factors)"
                )

    reason_counts: dict[str, int] = {}
    listing_dates = listing_dates or {
        code: pd.to_datetime(group["date"]).min()
        for code, group in out.groupby("code")
    }
    for factor in actual:
        if factor not in NON_OHLCV_FACTORS:
            continue
        firsts = (raw_first_obs or {}).get(factor, {})
        reasons = classify_missing_reasons(
            out,
            factor,
            listing_dates=listing_dates,
            raw_first_obs=firsts,
            download_failures=download_failures,
            margin_absence_kinds=margin_absence_kinds,
        )
        for key, value in reasons.value_counts().items():
            if key == "observed":
                continue
            reason_counts[f"{factor}:{key}"] = int(value)

    if list(actual) != list(factors):
        notes.append(f"declared={factors} actual={actual}")

    audit = FactorAudit(
        run_mode=run_mode,
        reproduction_status=status,
        declared_factors=list(factors),
        actual_factors=list(actual),
        factor_tiers=tiers,
        daily_coverage=daily_coverage,
        excluded_etf_count_by_date=excluded,
        etf_participation_ratio=participation,
        implicit_margin_screen=implicit_margin,
        missing_reason_counts=reason_counts,
        notes=notes,
    )
    return out, audit
