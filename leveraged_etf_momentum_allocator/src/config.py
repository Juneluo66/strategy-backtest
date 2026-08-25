"""Configuration loading — frozen original from verified QuantConnect source."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

ORIGINAL_ABORT_MESSAGE = (
    "Original QuantConnect rules have not been source-verified.\n"
    "Replication aborted to prevent fabricated parameters."
)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@dataclass(frozen=True)
class ProjectConfig:
    project_root: Path
    original: dict[str, Any]
    research: dict[str, Any]
    costs: dict[str, Any]

    @classmethod
    def load(cls, project_root: Optional[Path] = None) -> "ProjectConfig":
        root = Path(project_root or Path(__file__).resolve().parents[1])
        return cls(
            project_root=root,
            original=_load_yaml(root / "configs" / "original.yaml"),
            research=_load_yaml(root / "configs" / "research.yaml"),
            costs=_load_yaml(root / "configs" / "costs.yaml"),
        )

    @property
    def cache_dir(self) -> Path:
        return self.project_root / "data" / "cache"

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    def is_original_verified(self) -> bool:
        return bool(self.original.get("source_verified", False))

    def is_frozen(self) -> bool:
        return bool(self.original.get("frozen", False))

    def require_original_verification(self) -> None:
        if not self.is_original_verified():
            raise SourceVerificationError(ORIGINAL_ABORT_MESSAGE)

    def universe(self) -> list[str]:
        u = self.original.get("universe", [])
        if isinstance(u, list):
            return list(u)
        return list(u.get("tickers", []) or [])

    def target_assets(self) -> list[str]:
        return list(self.original.get("target_assets", []))

    def parameters(self) -> dict[str, Any]:
        return dict(self.original.get("parameters", {}))

    def thresholds(self) -> dict[str, Any]:
        return dict(self.original.get("thresholds", {}))

    def requested_start(self) -> str:
        return str(self.original.get("backtest", {}).get("requested_start", "2012-01-01"))

    def backtest_end(self) -> Optional[str]:
        return self.original.get("backtest", {}).get("end")

    def initial_cash(self) -> float:
        return float(self.original.get("backtest", {}).get("initial_cash", 100_000))

    def warmup_bars(self) -> int:
        return int(self.original.get("backtest", {}).get("warmup_bars", 200))

    def reconciliation_targets(self) -> dict[str, Any]:
        return dict(self.original.get("reconciliation_targets", {}))

    def reconciliation_tolerance(self) -> dict[str, float]:
        return dict(self.original.get("reconciliation_tolerance", {}))


class SourceVerificationError(RuntimeError):
    """Raised when original-mode backtest is attempted without verified rules."""
