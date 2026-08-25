"""Configuration for the dividend, low-volatility, quality strategy."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StrategyConfig:
    """Strategy, trading, and storage settings with conservative defaults."""

    project_root: Path = Path(__file__).resolve().parents[2]
    cache_dir: Path | None = None
    reports_dir: Path | None = None
    top_n: int = 25
    variant: str = "quality_industry"
    weighting: str = "inverse_volatility"
    dividend_signal: str = "annual_dividend_yield"
    high_dividend_percentile: float = 0.20
    excluded_industries: tuple[str, ...] = ()
    rebalance_month: str = "first_trading_day"
    rebalance_position: str = "first"
    volatility_window: int = 120
    dividend_years: int = 3
    min_listing_days: int = 365
    min_avg_turnover: float = 5_000_000.0
    max_dividend_yield: float = 0.20
    min_net_income: float = 0.0
    min_operating_cash_flow: float = 0.0
    max_debt_ratio: float = 0.85
    max_roe_std: float = 0.25
    max_order_to_avg_turnover: float = 0.10
    min_dividend_yield: float = 0.0
    max_industry_weight: float = 0.20
    max_stock_weight: float = 0.10
    commission_rate: float = 0.0003
    slippage_rate: float = 0.0005
    sell_stamp_duty_rate: float = 0.0005
    minimum_commission: float = 5.0
    initial_capital: float = 1_000_000.0
    annualization_days: int = 252

    def __post_init__(self) -> None:
        if self.cache_dir is None:
            object.__setattr__(self, "cache_dir", self.project_root / "data" / "cache")
        if self.reports_dir is None:
            object.__setattr__(self, "reports_dir", self.project_root / "reports")
        if self.top_n < 1:
            raise ValueError("top_n must be positive")
        if not 0 < self.max_industry_weight <= 1:
            raise ValueError("max_industry_weight must be in (0, 1]")
        if not 0 < self.max_stock_weight <= 1:
            raise ValueError("max_stock_weight must be in (0, 1]")
        if self.weighting not in {"equal", "inverse_volatility"}:
            raise ValueError("weighting must be 'equal' or 'inverse_volatility'")
        if self.variant not in {
            "dividend",
            "dividend_lowvol",
            "dividend_quality",
            "quality_industry",
            "strict_b",
            "legacy_b_score",
        }:
            raise ValueError("unknown strategy variant")
        if not 0 < self.high_dividend_percentile <= 1:
            raise ValueError("high_dividend_percentile must be in (0, 1]")
        if self.rebalance_position not in {"first", "middle", "last"}:
            raise ValueError("rebalance_position must be first, middle, or last")

    @property
    def one_way_cost(self) -> float:
        return self.commission_rate + self.slippage_rate
