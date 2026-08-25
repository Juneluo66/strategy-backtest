"""Hard status labels for research-data honesty."""
from __future__ import annotations

DATA_TIER_HISTORICAL_SP500 = "HISTORICAL_SP500_APPROX"
DATA_TIER_STATIC_PILOT = "SURVIVORSHIP_BIASED_PILOT"

SURVIVORSHIP_REDUCED = "REDUCED_NOT_ELIMINATED"
SURVIVORSHIP_FULL_BIAS = "CURRENT_CONSTITUENT_BACKFILL"

PIT_VALIDATED = False  # never true on free / historical-S&P500 paths

DELISTING_RETURN_UNAVAILABLE = "UNAVAILABLE"
DELISTING_RETURN_PROXY = "DELIST_PROXY"
INDEX_EXIT = "INDEX_EXIT"
SIZE_BLOCKED = "BLOCKED_BY_PIT_MARKET_CAP"


def research_status(*, historical_membership: bool) -> dict:
    """Return the mandatory status block for run metadata and reports."""
    if historical_membership:
        return {
            "DATA_TIER": DATA_TIER_HISTORICAL_SP500,
            "SURVIVORSHIP_BIAS": SURVIVORSHIP_REDUCED,
            "PIT_VALIDATED": False,
            "DELISTING_RETURN": DELISTING_RETURN_UNAVAILABLE,
            "SIZE_NEUTRAL": SIZE_BLOCKED,
        }
    return {
        "DATA_TIER": DATA_TIER_STATIC_PILOT,
        "SURVIVORSHIP_BIAS": SURVIVORSHIP_FULL_BIAS,
        "PIT_VALIDATED": False,
        "DELISTING_RETURN": DELISTING_RETURN_UNAVAILABLE,
        "SIZE_NEUTRAL": SIZE_BLOCKED,
    }
