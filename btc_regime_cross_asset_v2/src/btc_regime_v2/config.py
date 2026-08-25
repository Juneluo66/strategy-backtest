from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class V2Config:
    def __init__(self, project_root: Path | None = None):
        self.project_root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        path = self.project_root / "configs" / "research_v2.yaml"
        with path.open() as f:
            self.raw: dict[str, Any] = yaml.safe_load(f)

    @property
    def prices_dir(self) -> Path:
        return self.project_root / "data" / "prices"

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    @property
    def shared_v1_prices_dir(self) -> Path | None:
        rel = self.raw.get("data", {}).get("shared_v1_prices_dir")
        if not rel:
            return None
        return (self.project_root / rel).resolve()

    def all_symbols(self) -> list[str]:
        m = self.raw["matrix"]
        off_rules = self.raw.get("off_rules_v2", {})
        extra: list[str] = []
        for rule in off_rules.values():
            if "trend_asset" in rule:
                extra.append(rule["trend_asset"])
            if "fallback_asset" in rule:
                extra.append(rule["fallback_asset"])
        syms = list(m["risk_on"]) + list(m["risk_off"]) + extra
        btc = self.raw["data"].get("btc_symbol", "BTC-USD")
        seen: set[str] = set()
        out: list[str] = []
        for s in [btc, *syms]:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out
