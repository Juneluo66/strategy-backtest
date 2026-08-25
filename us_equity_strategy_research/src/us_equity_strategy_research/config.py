"""Frozen configuration loader."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass(frozen=True)
class ResearchConfig:
    project_root: Path
    raw: dict
    universe: dict

    @property
    def cache_dir(self) -> Path:
        return self.project_root / "data" / "cache"

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    @property
    def return_basis(self) -> str:
        return str(self.raw.get("return_basis", "Yahoo_AdjClose_scaled_Open"))

    def section(self, name: str) -> dict[str, Any]:
        return dict(self.raw.get(name, {}))


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_config(project_root: Optional[Path] = None, config_name: str = "frozen.yaml") -> ResearchConfig:
    root = project_root or Path(__file__).resolve().parents[2]
    raw = load_yaml(root / "configs" / config_name)
    if config_name != "frozen.yaml" and raw.get("inherits"):
        base = load_yaml(root / "configs" / "frozen.yaml")
        merged = {**base, **{k: v for k, v in raw.items() if k != "inherits"}}
        raw = merged
    universe = load_yaml(root / "configs" / "universe.yaml")
    required = {"data", "costs", "research_windows", "multifactor", "momentum", "pead"}
    missing = required - raw.keys()
    if missing:
        raise ValueError(f"configuration missing keys: {sorted(missing)}")
    return ResearchConfig(root, raw, universe)
