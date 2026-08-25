"""Frozen configuration loader."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

ALLOWED_VERSIONS = [
    "base_12_1_top3",
    "composite_6_1_12_1_top3",
    "composite_top3_buffer",
]


@dataclass(frozen=True)
class SectorConfig:
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
        """All Yahoo symbols needed (sectors + benchmarks + RF)."""
        out = list(dict.fromkeys(self.sectors + self.benchmarks + [self.rf_primary, self.rf_proxy]))
        return out

    @property
    def panel_symbols(self) -> list[str]:
        """Strict common panel for strategy + formal benchmarks (no RF)."""
        return list(dict.fromkeys(self.sectors + self.benchmarks))

    @property
    def return_basis(self) -> str:
        return str(self.raw["data"]["return_basis"])

    @property
    def one_way_bps(self) -> float:
        return float(self.raw["one_way_bps"])

    @property
    def challenger(self) -> str:
        return str(self.raw["challenger"])


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_config(project_root: Optional[Path] = None) -> SectorConfig:
    root = project_root or Path(__file__).resolve().parents[2]
    raw = load_yaml(root / "configs" / "frozen.yaml")
    universe = load_yaml(root / "configs" / "universe.yaml")
    required = {
        "versions",
        "challenger",
        "top_n",
        "one_way_bps",
        "data",
        "benchmarks_formal",
        "stability",
    }
    missing = required - raw.keys()
    if missing:
        raise ValueError(f"frozen configuration missing: {sorted(missing)}")
    if list(raw["versions"]) != ALLOWED_VERSIONS:
        raise ValueError(f"versions must be exactly {ALLOWED_VERSIONS}")
    if int(raw["top_n"]) != 3:
        raise ValueError("top_n frozen at 3")
    if int(raw.get("buffer_rank", 4)) != 4:
        raise ValueError("buffer_rank frozen at 4")
    if list(universe["sectors"]) != [
        "XLB",
        "XLE",
        "XLF",
        "XLI",
        "XLK",
        "XLP",
        "XLU",
        "XLV",
        "XLY",
    ]:
        raise ValueError("sector universe must be the fixed nine 1998 Select Sector SPDRs")
    forbidden = {"XLRE", "XLC"}
    if forbidden & set(universe["sectors"]):
        raise ValueError("XLRE/XLC are forbidden")
    if raw.get("ibkr_modified", False):
        raise ValueError("ibkr_modified must remain false")
    return SectorConfig(root, raw, universe)
