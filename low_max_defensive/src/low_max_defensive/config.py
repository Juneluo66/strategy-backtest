"""Paths and frozen config loader for low_max_defensive."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "cache"
REPORTS_DIR = ROOT / "reports"
CONFIG_PATH = ROOT / "configs" / "frozen.yaml"


@dataclass
class FrozenConfig:
    raw: dict[str, Any]
    cache_dir: Path = CACHE_DIR
    reports_dir: Path = REPORTS_DIR

    @property
    def lookback(self) -> int:
        return int(self.raw["signal_lookback_days"])

    @property
    def top_returns(self) -> int:
        return int(self.raw["top_returns"])

    @property
    def one_way_bps(self) -> float:
        return float(self.raw["costs"]["one_way_bps"])

    @property
    def min_dollar_volume(self) -> float:
        return float(self.raw["min_dollar_volume"])

    @property
    def portfolio_decile(self) -> float:
        return float(self.raw["portfolio_decile"])

    @property
    def max_portfolio_size(self) -> int:
        return int(self.raw["max_portfolio_size"])


def load_config(path: Path = CONFIG_PATH) -> FrozenConfig:
    return FrozenConfig(raw=yaml.safe_load(path.read_text(encoding="utf-8")))
