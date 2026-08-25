"""Frozen configuration loader."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass(frozen=True)
class TrendConfig:
    project_root: Path
    raw: dict
    universe: dict

    @property
    def cache_dir(self) -> Path:
        return self.project_root / "data" / "cache"

    @property
    def prices_dir(self) -> Path:
        return self.cache_dir / "prices"

    @property
    def snapshots_dir(self) -> Path:
        return self.project_root / "data" / "snapshots"

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    @property
    def risk_symbols(self) -> list[str]:
        return list(self.universe["risk"])

    @property
    def cash_symbol(self) -> str:
        return str(self.universe["cash"])

    @property
    def all_symbols(self) -> list[str]:
        return self.risk_symbols + [self.cash_symbol]

    @property
    def return_basis(self) -> str:
        return str(self.raw["data"]["return_basis"])

    @property
    def one_way_bps(self) -> float:
        return float(self.raw["one_way_bps"])

    @property
    def vol_lookback_days(self) -> int:
        return int(self.raw["vol_lookback_days"])

    def asset_groups(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self.universe["asset_groups"].items()}


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_config(project_root: Optional[Path] = None) -> TrendConfig:
    root = project_root or Path(__file__).resolve().parents[2]
    raw = load_yaml(root / "configs" / "frozen.yaml")
    universe = load_yaml(root / "configs" / "universe.yaml")
    required = {
        "versions",
        "lookbacks_months",
        "vol_lookback_days",
        "one_way_bps",
        "data",
        "benchmarks_formal",
        "stability",
    }
    missing = required - raw.keys()
    if missing:
        raise ValueError(f"frozen configuration missing: {sorted(missing)}")
    if list(raw["versions"]) != ["base_12m_equal", "ensemble_equal", "ensemble_risk_balanced"]:
        raise ValueError("versions must be exactly the three pre-registered names")
    if list(raw["lookbacks_months"]) != [3, 6, 12]:
        raise ValueError("lookbacks_months frozen at [3, 6, 12]")
    if int(raw["vol_lookback_days"]) != 63:
        raise ValueError("vol_lookback_days frozen at 63")
    return TrendConfig(root, raw, universe)
