"""Frozen configuration and parameter integrity checks."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


@dataclass(frozen=True)
class MaxEffectConfig:
    project_root: Path
    raw: dict

    @property
    def cache_dir(self) -> Path:
        return self.project_root / "data" / "cache"

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"


def load_config(project_root: Optional[Path] = None) -> MaxEffectConfig:
    root = project_root or Path(__file__).resolve().parents[2]
    with (root / "configs" / "frozen.yaml").open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    required = {"signal_lookback_days", "top_returns", "max_portfolio_size", "vix", "variants"}
    missing = required - raw.keys()
    if missing:
        raise ValueError(f"frozen configuration missing: {sorted(missing)}")
    if raw["top_returns"] > raw["signal_lookback_days"]:
        raise ValueError("top_returns cannot exceed signal lookback")
    return MaxEffectConfig(root, raw)
