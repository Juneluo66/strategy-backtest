"""Frozen configuration loader."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass(frozen=True)
class DualMomentumConfig:
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
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    def variant(self, name: str) -> dict[str, Any]:
        variants = self.raw["variants"]
        if name not in variants:
            raise KeyError(f"unknown variant: {name}; known={sorted(variants)}")
        return dict(variants[name])

    def pool_symbols(self, pool_name: str) -> list[str]:
        pool = self.universe[pool_name]
        return list(pool["risk"]) + [pool["cash"]]

    def category_map(self) -> dict[str, str]:
        """Map ticker -> category name for non-cash assets."""
        mapping: dict[str, str] = {}
        for category, symbols in self.universe["categories"].items():
            if category == "cash":
                continue
            for symbol in symbols:
                mapping[symbol] = category
        return mapping


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_config(project_root: Optional[Path] = None) -> DualMomentumConfig:
    root = project_root or Path(__file__).resolve().parents[2]
    raw = load_yaml(root / "configs" / "frozen.yaml")
    universe = load_yaml(root / "configs" / "universe.yaml")
    required = {
        "momentum",
        "trend_filter",
        "volatility",
        "portfolio",
        "hysteresis",
        "cash",
        "costs",
        "variants",
        "data",
    }
    missing = required - raw.keys()
    if missing:
        raise ValueError(f"frozen configuration missing: {sorted(missing)}")
    return DualMomentumConfig(root, raw, universe)
