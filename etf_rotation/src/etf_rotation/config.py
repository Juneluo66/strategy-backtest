"""Frozen research configuration and reproducibility checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


@dataclass(frozen=True)
class RotationConfig:
    """Research parameters shared by selection and both backtest engines."""

    project_root: Path = PROJECT_ROOT
    cache_dir: Path | None = None
    reports_dir: Path | None = None
    universe_mode: str = "A_SHARE_ONLY"
    lookback: int = 252
    frequency: int = 5
    position_size: int = 2
    commission_a_share: float = 0.0002
    commission_qdii: float = 0.0005
    slippage_rate: float = 0.0
    max_order_adv_pct: float = 1.0
    initial_capital: float = 1_000_000.0
    delta_rank: float = 0.10
    min_hold_days: int = 9
    max_replacements: int = 1
    regime_proxy: str = "510300"
    regime_window: int = 20
    regime_thresholds: tuple[float, ...] = (25.0, 30.0, 40.0)
    regime_exposures: tuple[float, ...] = (1.0, 0.7, 0.4, 0.1)
    training_end: str = "2025-04-30"
    oos_start: str = "2025-05-01"
    variant: str = "R1"
    factor_set: str = "momentum"
    use_hysteresis: bool = True
    use_regime_gate: bool = True
    allow_qdii_trading: bool = False
    factor_weights: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cache_dir is None:
            object.__setattr__(self, "cache_dir", self.project_root / "data" / "cache")
        if self.reports_dir is None:
            object.__setattr__(self, "reports_dir", self.project_root / "reports")
        if self.frequency < 1 or self.position_size < 1 or self.lookback < 20:
            raise ValueError("frequency, position_size, and lookback must be positive")
        if not 0 <= self.delta_rank <= 1 or self.min_hold_days < 0:
            raise ValueError("invalid hysteresis settings")
        if len(self.regime_exposures) != len(self.regime_thresholds) + 1:
            raise ValueError("regime exposures require one more element than thresholds")
        if self.universe_mode not in {"A_SHARE_ONLY", "GLOBAL"}:
            raise ValueError("universe_mode must be A_SHARE_ONLY or GLOBAL")


def frozen_config(path: Path | None = None, **overrides: Any) -> RotationConfig:
    """Load the sealed v8 reference and allow explicit research overrides."""
    data = load_yaml(path or PROJECT_ROOT / "configs" / "frozen_v8.yaml")
    hysteresis = data["hysteresis"]
    regime = data["regime_gate"]
    config = RotationConfig(
        universe_mode=data["universe_mode"],
        lookback=data["lookback"],
        frequency=data["frequency"],
        position_size=data["position_size"],
        commission_a_share=data["commission_a_share"],
        commission_qdii=data["commission_qdii"],
        initial_capital=data["initial_capital"],
        delta_rank=hysteresis["delta_rank"],
        min_hold_days=hysteresis["min_hold_days"],
        max_replacements=hysteresis["max_replacements"],
        regime_proxy=regime["proxy"],
        regime_window=regime["window"],
        regime_thresholds=tuple(regime["percentile_thresholds"]),
        regime_exposures=tuple(regime["exposures"]),
        training_end=data["training_end"],
        oos_start=data["oos_start"],
    )
    return RotationConfig(**{**config.__dict__, **overrides})


def sealed_parameter_check(config: RotationConfig, *, allow_unfrozen: bool = False) -> None:
    """Reject accidental production-parameter drift at command entry."""
    if allow_unfrozen:
        return
    frozen = frozen_config()
    protected = (
        "frequency", "position_size", "delta_rank", "min_hold_days", "max_replacements",
        "regime_proxy", "regime_window", "regime_thresholds", "regime_exposures",
        "commission_a_share", "commission_qdii", "universe_mode",
    )
    drift = {name: (getattr(frozen, name), getattr(config, name)) for name in protected
             if getattr(frozen, name) != getattr(config, name)}
    if drift:
        raise ValueError(f"frozen v8 parameters changed: {drift}; pass --allow-unfrozen for research")


def strategy_definition(config: RotationConfig, name: str) -> tuple[list[str], list[float], list[float]]:
    """Read every production factor declaration from the single frozen YAML."""
    if name == "momentum":
        return ["MOM_20D"], [1.0], [1.0]
    data = load_yaml(config.project_root / "configs" / "frozen_v8.yaml")
    selected = data["strategies"][name]
    return selected["factors"], selected["signs"], selected["icirs"]
