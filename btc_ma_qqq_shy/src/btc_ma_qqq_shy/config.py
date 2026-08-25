from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ProjectConfig:
    def __init__(self, project_root: Path | None = None):
        self.project_root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        path = self.project_root / "configs" / "frozen.yaml"
        with path.open() as f:
            self.raw: dict[str, Any] = yaml.safe_load(f)

    @property
    def prices_dir(self) -> Path:
        return self.project_root / "data" / "prices"

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    @property
    def symbols(self) -> list[str]:
        d = self.raw["data"]
        out = [d["btc_symbol"], d["risk_on"], d["risk_off"], *d["benchmarks"]]
        # preserve order, unique
        seen: set[str] = set()
        uniq: list[str] = []
        for s in out:
            if s not in seen:
                seen.add(s)
                uniq.append(s)
        return uniq
