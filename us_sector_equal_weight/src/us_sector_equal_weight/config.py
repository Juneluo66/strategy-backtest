"""Frozen configuration loader for sector equal-weight research."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

ALLOWED_VERSIONS = ["EW9_monthly", "EW9_quarterly", "EW9_annual"]
FIXED_SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]


@dataclass(frozen=True)
class EWConfig:
    project_root: Path
    raw: dict
    universe: dict
    french_mapping: dict

    @property
    def cache_dir(self) -> Path:
        return self.project_root / "data" / "cache"

    @property
    def prices_dir(self) -> Path:
        return self.cache_dir / "prices"

    @property
    def french_dir(self) -> Path:
        return self.cache_dir / "french"

    @property
    def snapshots_dir(self) -> Path:
        return self.project_root / "data" / "snapshots"

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    @property
    def sectors(self) -> list[str]:
        return list(self.universe["sectors"])

    @property
    def benchmarks(self) -> list[str]:
        return list(self.universe["benchmarks"])

    @property
    def rf_primary(self) -> str:
        return str(self.universe["rf_primary"])

    @property
    def rf_proxy(self) -> str:
        return str(self.universe["rf_proxy_pre_bil"])

    @property
    def price_symbols(self) -> list[str]:
        return list(dict.fromkeys(self.sectors + self.benchmarks + [self.rf_primary, self.rf_proxy]))

    @property
    def panel_symbols(self) -> list[str]:
        # Strategy + SPY for discovery common panel (RSP may start later)
        return list(dict.fromkeys(self.sectors + ["SPY"]))

    @property
    def return_basis(self) -> str:
        return str(self.raw["data"]["return_basis"])

    @property
    def one_way_bps(self) -> float:
        return float(self.raw["one_way_bps"])

    @property
    def versions(self) -> list[str]:
        return list(self.raw["versions"])


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_config(project_root: Optional[Path] = None) -> EWConfig:
    root = project_root or Path(__file__).resolve().parents[2]
    raw = load_yaml(root / "configs" / "frozen.yaml")
    universe = load_yaml(root / "configs" / "universe.yaml")
    french = load_yaml(root / "configs" / "french_mapping.yaml")
    if list(raw["versions"]) != ALLOWED_VERSIONS:
        raise ValueError(f"versions must be exactly {ALLOWED_VERSIONS}")
    if list(universe["sectors"]) != FIXED_SECTORS:
        raise ValueError("sector universe must be the fixed nine 1998 Select Sector SPDRs")
    if raw.get("sector_ranking") or raw.get("trend_filter") or raw.get("sma_filter"):
        raise ValueError("ranking/trend/sma filters are forbidden in this track")
    if raw.get("bil_sleeve") is True or raw.get("vol_weighting") is True:
        raise ValueError("cash sleeve / vol weighting forbidden")
    if raw.get("leverage") not in (None, False, "none", "null"):
        raise ValueError("leverage forbidden in this track")
    if raw.get("ibkr_modified", False):
        raise ValueError("ibkr_modified must remain false")
    if not raw.get("equal_weight", False):
        raise ValueError("equal_weight must be true")
    return EWConfig(root, raw, universe, french)
