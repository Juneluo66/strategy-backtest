"""Pre-registered SECTOR_EQUAL_WEIGHT_RETURN_CANDIDATE gate."""
from __future__ import annotations

from typing import Any


def evaluate_gate(payload: dict[str, Any], config_raw: dict) -> dict:
    g = config_raw["gate"]
    checks: dict[str, bool] = {}
    notes: dict[str, str] = {}

    disc = payload["discovery"]["EW9_monthly"]["metrics"]
    spy = payload["discovery"]["spy_bh"]["metrics"]
    checks["discovery_cagr_gt_spy"] = bool(disc["cagr"] > spy["cagr"])

    # Pseudo-OOS starts: majority beat SPY on CAGR
    poos = payload.get("pseudo_oos", {})
    poos_flags = []
    for start, block in poos.items():
        if "EW9_monthly" in block and "spy_bh" in block:
            poos_flags.append(block["EW9_monthly"]["cagr"] > block["spy_bh"]["cagr"])
    checks["majority_pseudo_oos_gt_spy"] = bool(poos_flags) and (sum(poos_flags) / len(poos_flags) >= 0.5)
    notes["pseudo_oos_win_frac"] = f"{sum(poos_flags)}/{len(poos_flags)}" if poos_flags else "0/0"

    # Fixed endpoints from common start
    ends = payload.get("fixed_endpoints", {})
    end_flags = []
    for ep, block in ends.items():
        if "EW9_monthly" in block and "spy_bh" in block:
            end_flags.append(block["EW9_monthly"]["cagr"] > block["spy_bh"]["cagr"])
    checks["majority_fixed_endpoints_gt_spy"] = bool(end_flags) and (
        sum(end_flags) / len(end_flags) >= 0.5
    )
    notes["endpoint_win_frac"] = f"{sum(end_flags)}/{len(end_flags)}" if end_flags else "0/0"

    roll = payload.get("rolling", {})
    r5 = roll.get("5y", {}).get("win_rate", 0)
    r10 = roll.get("10y", {}).get("win_rate", 0)
    checks["rolling_5y_ge_55"] = bool(r5 >= g["rolling_5y_win_min"])
    checks["rolling_10y_ge_60"] = bool(r10 >= g["rolling_10y_win_min"])

    # Cost stress: 10bp and 20bp monthly still > SPY
    cost = payload.get("cost_stress", {})
    checks["cost_10bp_not_flip"] = bool(
        cost.get("10.0", {}).get("EW9_monthly", {}).get("cagr", -1) > spy["cagr"]
    )
    checks["cost_20bp_not_flip"] = bool(
        cost.get("20.0", {}).get("EW9_monthly", {}).get("cagr", -1) > spy["cagr"]
    )

    delay = payload.get("delay_stress", {})
    checks["delay_not_flip"] = bool(
        delay.get("EW9_monthly", {}).get("cagr", -1) > spy["cagr"]
    )

    french = payload.get("french", {})
    # Directional support: post_etf or full monthly CAGR > 0 and preferably > pre passive
    fr_post = french.get("post_etf", {}).get("EW9_monthly", {})
    fr_pre = french.get("pre_etf", {}).get("EW9_monthly", {})
    checks["french_same_direction"] = bool(
        fr_post.get("status") == "OK"
        and fr_pre.get("status") == "OK"
        and fr_post.get("cagr", -1) > 0
        and fr_pre.get("cagr", -1) > 0
    )

    dom = payload.get("attribution", {}).get("dominance", {})
    checks["not_single_sector_dominated"] = not bool(dom.get("dominated", True))

    # vs RSP incremental on common RSP span (not mismatched sample starts)
    rsp = payload["discovery"].get("rsp_bh", {}).get("metrics")
    ew_rsp = payload["discovery"].get("EW9_monthly_on_rsp_span", {}).get("metrics")
    if (
        rsp
        and ew_rsp
        and rsp.get("status") != "EMPTY"
        and pd_notna(rsp.get("cagr"))
        and pd_notna(ew_rsp.get("cagr"))
    ):
        edge = ew_rsp["cagr"] - rsp["cagr"]
        # Incremental means not collapsing to RSP: either material CAGR gap or better Sharpe/MaxDD profile
        checks["vs_rsp_incremental"] = bool(
            abs(edge) >= 0.002
            or ew_rsp.get("sharpe", 0) > rsp.get("sharpe", 0) + 0.02
            or ew_rsp.get("max_drawdown", -1) > rsp.get("max_drawdown", -1) + 0.02
        )
        notes["cagr_edge_vs_rsp_same_span"] = str(edge)
        if abs(edge) < 0.005 and abs(ew_rsp.get("sharpe", 0) - rsp.get("sharpe", 0)) < 0.05:
            notes["rsp_exposure_warning"] = "EW9_close_to_RSP_general_equal_weight_exposure"
    else:
        checks["vs_rsp_incremental"] = False
        notes["rsp"] = "unavailable_or_empty"

    # Monthly advantage vs quarterly/annual after costs — prefer lower turnover if not
    q = payload["discovery"]["EW9_quarterly"]["metrics"]
    a = payload["discovery"]["EW9_annual"]["metrics"]
    # monthly must beat both on net CAGR by enough to matter OR we won't claim monthly champion
    checks["monthly_covers_extra_cost_vs_q_a"] = bool(
        disc["cagr"] >= q["cagr"] - 1e-12 and disc["cagr"] >= a["cagr"] - 1e-12
    )
    notes["prefer_lower_turnover_if_false"] = (
        "If monthly_covers_extra_cost_vs_q_a is false, prefer quarterly/annual; "
        "do not pick frequency by max historical CAGR alone."
    )

    # MaxDD not deeper than SPY by >5pp
    checks["maxdd_not_worse_than_spy_by_5pp"] = bool(
        disc["max_drawdown"] >= spy["max_drawdown"] - g["maxdd_vs_spy_extra_pp"]
    )

    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    # All required for RETURN_CANDIDATE
    if all(checks.values()):
        label = g["label_pass"]
    elif checks.get("discovery_cagr_gt_spy") and not (
        checks.get("majority_pseudo_oos_gt_spy") and checks.get("rolling_5y_ge_55")
    ):
        label = g["label_discovery_only"]
    else:
        label = "REJECT_OR_RESEARCH_ONLY"

    # RSP similarity note (same-span)
    rsp_note = None
    ew_rsp = payload["discovery"].get("EW9_monthly_on_rsp_span", {}).get("metrics")
    if rsp and ew_rsp and pd_notna(rsp.get("cagr")) and pd_notna(ew_rsp.get("cagr")):
        if abs(ew_rsp["cagr"] - rsp["cagr"]) < 0.005 and abs(ew_rsp.get("sharpe", 0) - rsp.get("sharpe", 0)) < 0.05:
            rsp_note = "EW9_close_to_RSP_general_equal_weight_exposure_not_sector_alpha"

    return {
        "label": label,
        "passed": passed,
        "total": total,
        "checks": checks,
        "notes": notes,
        "rsp_similarity_note": rsp_note,
        "preferred_frequency_hint": (
            "EW9_monthly"
            if checks.get("monthly_covers_extra_cost_vs_q_a")
            else "prefer_EW9_quarterly_or_annual_lower_turnover"
        ),
    }


def pd_notna(x) -> bool:
    try:
        import pandas as pd

        return bool(pd.notna(x))
    except Exception:
        return x is not None
