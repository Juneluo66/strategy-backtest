"""Load non-OHLCV factor frames from production or research staging."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from etf_rotation.config import RotationConfig

NON_OHLCV_FACTORS = (
    "MARGIN_BUY_RATIO",
    "MARGIN_CHG_10D",
    "SHARE_CHG_5D",
    "SHARE_CHG_20D",
)

TIER_PRODUCTION = "production"
TIER_RESEARCH_STAGING = "research_staging"
TIER_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class FactorSource:
    factor: str
    tier: str
    path: Path | None
    frame: pd.DataFrame | None
    source_version: str | None = None


def non_ohlcv_root(config: RotationConfig) -> Path:
    return Path(config.cache_dir) / "non_ohlcv"


def production_manifest_path(config: RotationConfig) -> Path:
    return non_ohlcv_root(config) / "production_manifest.json"


def _read_long_factor(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    if "value" not in frame.columns or "date" not in frame.columns or "code" not in frame.columns:
        raise ValueError(f"{path} must contain date, code, value")
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    out["code"] = out["code"].astype(str).str.zfill(6)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    return out


def _production_factors(config: RotationConfig) -> set[str]:
    path = production_manifest_path(config)
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    factors = data.get("factors") or []
    # Per-factor promotion: only listed factors count as production.
    if data.get("factor_tiers"):
        return {
            name for name, tier in data["factor_tiers"].items()
            if tier == TIER_PRODUCTION
        }
    if data.get("status") == "production":
        return {str(item) for item in factors} if factors else set(NON_OHLCV_FACTORS)
    return {str(item) for item in factors}


def _latest_staging_dir(config: RotationConfig) -> Path | None:
    root = non_ohlcv_root(config) / "staging"
    if not root.exists():
        return None
    dirs = sorted([path for path in root.iterdir() if path.is_dir()], key=lambda p: p.name)
    return dirs[-1] if dirs else None


def resolve_factor_source(config: RotationConfig, factor: str) -> FactorSource:
    """Prefer production when that factor is promoted; else latest staging."""
    if factor not in NON_OHLCV_FACTORS:
        return FactorSource(factor, TIER_UNAVAILABLE, None, None)
    promoted = _production_factors(config)
    prod_path = non_ohlcv_root(config) / f"{factor}.parquet"
    if factor in promoted and prod_path.exists():
        frame = _read_long_factor(prod_path)
        version = None
        manifest = production_manifest_path(config)
        if manifest.exists():
            version = json.loads(manifest.read_text(encoding="utf-8")).get("source_version")
        return FactorSource(factor, TIER_PRODUCTION, prod_path, frame, version)

    staging = _latest_staging_dir(config)
    if staging is not None:
        path = staging / f"{factor}.parquet"
        if path.exists():
            return FactorSource(
                factor, TIER_RESEARCH_STAGING, path, _read_long_factor(path), staging.name
            )
    return FactorSource(factor, TIER_UNAVAILABLE, None, None)


def load_non_ohlcv_sources(config: RotationConfig) -> dict[str, FactorSource]:
    return {factor: resolve_factor_source(config, factor) for factor in NON_OHLCV_FACTORS}


def merge_factor_into_panel(panel: pd.DataFrame, source: FactorSource) -> pd.DataFrame:
    """Left-join factor values by date/code. NaNs preserved; no fill."""
    out = panel.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    out["code"] = out["code"].astype(str).str.zfill(6)
    if source.frame is None or source.frame.empty:
        out[source.factor] = np.nan
        return out
    slim = source.frame[["date", "code", "value"]].rename(columns={"value": source.factor})
    before_na = True  # documentation: left merge never fills missing with 0
    merged = out.merge(slim, on=["date", "code"], how="left")
    assert before_na
    return merged
