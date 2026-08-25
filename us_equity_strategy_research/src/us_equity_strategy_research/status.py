"""Hard status labels and phase-stop helpers (H1–H6)."""
from __future__ import annotations

DATA_TIER = "HISTORICAL_SP500_APPROX"
SURVIVORSHIP_BIAS = "REDUCED_NOT_ELIMINATED"
PIT_VALIDATED = False

INDEX_EXIT = "INDEX_EXIT"
DELISTING = "DELISTING"
DELISTING_RETURN_UNAVAILABLE = "UNAVAILABLE"
DELIST_PROXY = "DELIST_PROXY"

SIZE_BLOCKED = "BLOCKED_BY_PIT_MARKET_CAP"
EARNINGS_SURPRISE_BLOCKED = "BLOCKED"
PEAD_PROXY = "PEAD_PROXY"
RETURN_BASIS = "Yahoo_AdjClose_scaled_Open"


def research_status(
    *,
    has_pit_fundamentals: bool = False,
    has_earnings_surprise: bool = False,
    has_delisting_returns: bool = False,
) -> dict:
    return {
        "DATA_TIER": DATA_TIER,
        "SURVIVORSHIP_BIAS": SURVIVORSHIP_BIAS,
        "PIT_VALIDATED": False,
        "DELISTING_RETURN": "AVAILABLE" if has_delisting_returns else DELISTING_RETURN_UNAVAILABLE,
        "SIZE_NEUTRAL": SIZE_BLOCKED,
        "PIT_FUNDAMENTALS": "OK" if has_pit_fundamentals else "BLOCKED",
        "EARNINGS_SURPRISE": "OK" if has_earnings_surprise else EARNINGS_SURPRISE_BLOCKED,
        "return_basis": RETURN_BASIS,
    }


class PhaseStop(Exception):
    """Raised when a phase hard-stop condition triggers (H6)."""


def assert_not_mix_exit_types(event: str) -> None:
    if event not in {INDEX_EXIT, DELISTING, DELIST_PROXY}:
        raise ValueError(f"unknown corporate event type: {event}")


def gate_equity_for_portfolio(strategy_grade: str, *, is_pead_proxy: bool = False) -> bool:
    """Only PASS / CONDITIONAL PASS equity strategies may enter P2/P3/P5."""
    if is_pead_proxy:
        return False
    return strategy_grade in {"PASS", "CONDITIONAL PASS"}
