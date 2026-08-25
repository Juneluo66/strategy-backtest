from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class IbkrLiveConfig:
    def __init__(self, project_root: Path | None = None):
        root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        self.project_root = root
        path = root / "configs" / "ibkr_live.yaml"
        with path.open() as f:
            self.raw: dict[str, Any] = yaml.safe_load(f)

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    def ledger_path(self) -> Path:
        rel = self.raw["ledger"]["path"]
        return self.project_root / rel

    def initial_nav_path(self) -> Path:
        rel = self.raw["ledger"]["initial_nav_path"]
        return self.project_root / rel

    def report_path(self) -> Path:
        rel = self.raw["ledger"]["report_path"]
        return self.project_root / rel
