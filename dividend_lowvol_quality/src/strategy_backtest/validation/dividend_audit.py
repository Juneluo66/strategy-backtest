"""Auditable comparison of dividend-yield definitions."""
from __future__ import annotations

import pandas as pd

from strategy_backtest.data.pit import dividend_metrics_as_of, normalize_dividend_events


def audit_dividends(
    events: pd.DataFrame, prices: pd.DataFrame, code: str, as_of: object
) -> tuple[pd.DataFrame, dict[str, float | int]]:
    """Return all event decisions and the two reconstructed yield definitions."""
    eligible, rejected = normalize_dividend_events(events)
    price = prices.copy()
    price["date"] = pd.to_datetime(price["date"])
    cutoff = pd.Timestamp(as_of).normalize()
    observed = price[price["date"] <= cutoff].sort_values("date")
    if observed.empty:
        raise ValueError(f"no close available for {code} on or before {cutoff.date()}")
    close = float(observed.iloc[-1]["close"])
    metrics = dividend_metrics_as_of(eligible, code, cutoff, close)
    audit = pd.concat(
        [
            eligible.assign(audit_decision="eligible"),
            rejected.assign(audit_decision=lambda x: "rejected:" + x["audit_reason"]),
        ],
        ignore_index=True,
    ).sort_values(["public_date", "ex_date"], na_position="last")
    return audit, {**metrics, "close": close, "eligible_event_count": len(eligible)}


def audit_dividend_stages(
    events: pd.DataFrame, prices: pd.DataFrame, code: str, as_of: object
) -> tuple[pd.DataFrame, dict[str, float | int]]:
    """Audit each dividend lifecycle without leaking finalized cash backwards.

    Free BaoStock/Cninfo records normally publish the cash amount only in the
    implementation record.  Therefore pre-implementation stage yields are
    explicitly unavailable instead of reusing a future finalized amount.
    """
    audit, metrics = audit_dividends(events, prices, code, as_of)
    cutoff = pd.Timestamp(as_of).normalize()
    stage_dates = {
        "plan": "plan_announce_date",
        "agm": "agm_date",
        "implementation_announcement": "implement_announce_date",
        "implemented": "ex_date",
    }
    for stage, column in stage_dates.items():
        if column not in audit:
            audit[f"{stage}_visible"] = False
        else:
            audit[f"{stage}_visible"] = pd.to_datetime(audit[column], errors="coerce").le(cutoff)
    audit["stage_cash_available"] = audit["implemented_visible"]
    audit["stage_audit_reason"] = ""
    audit.loc[
        audit["plan_visible"] & ~audit["stage_cash_available"], "stage_audit_reason"
    ] = "future_final_cash_not_backfilled"
    return audit, {
        **metrics,
        "plan_visible_events": int(audit["plan_visible"].sum()),
        "agm_visible_events": int(audit["agm_visible"].sum()),
        "implementation_visible_events": int(audit["implementation_announcement_visible"].sum()),
        "implemented_visible_events": int(audit["implemented_visible"].sum()),
    }
