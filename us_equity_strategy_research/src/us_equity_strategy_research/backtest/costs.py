"""Cost model — three scenarios; not a flat 1bp for all names."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostScenario:
    name: str
    commission_bps: float
    half_spread_bps: float
    impact_coeff_bps: float


SCENARIOS = {
    "optimistic": CostScenario("optimistic", 0.0, 1.0, 2.0),
    "baseline": CostScenario("baseline", 1.0, 2.5, 5.0),
    "stress": CostScenario("stress", 2.0, 5.0, 10.0),
}


def trade_cost_fraction(
    turnover: float,
    *,
    scenario: CostScenario,
    avg_adv_participation: float = 0.0,
    illiquid_boost: float = 1.0,
) -> float:
    """Approximate one-way cost on L1 turnover as a portfolio return drag."""
    base_bps = scenario.commission_bps + scenario.half_spread_bps
    impact_bps = scenario.impact_coeff_bps * max(avg_adv_participation, 0.0) * 100
    total_bps = (base_bps + impact_bps) * illiquid_boost
    return float(turnover * total_bps / 10_000.0)


def etf_flat_cost(turnover: float, one_way_bps: float = 5.0) -> float:
    return float(turnover * one_way_bps / 10_000.0)
