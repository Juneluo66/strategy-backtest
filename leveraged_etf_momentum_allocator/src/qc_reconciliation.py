"""QuantConnect daily equity reconciliation — import when QC exports available."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd


def compare_qc_local(
    qc_equity: pd.Series,
    local_equity: pd.Series,
    qc_orders: Optional[pd.DataFrame] = None,
) -> dict[str, Any]:
    """Compare QC vs local NAV series. Do not fabricate QC data."""
    qc = qc_equity.copy()
    local = local_equity.copy()
    qc.index = pd.to_datetime(qc.index)
    local.index = pd.to_datetime(local.index)
    aligned = pd.concat([qc.rename("qc"), local.rename("local")], axis=1).dropna()
    if aligned.empty:
        return {"error": "no overlapping dates", "status": "NO_DATA"}

    qc_norm = aligned["qc"] / aligned["qc"].iloc[0]
    loc_norm = aligned["local"] / aligned["local"].iloc[0]
    diff = loc_norm - qc_norm
    qc_ret = qc_norm.pct_change().dropna()
    loc_ret = loc_norm.pct_change().dropna()
    ret_aligned = pd.concat([qc_ret.rename("qc"), loc_ret.rename("local")], axis=1).dropna()

    first_div_idx = diff.abs().idxmax()
    result: dict[str, Any] = {
        "status": "OK",
        "n_days": len(aligned),
        "nav_correlation": float(aligned["qc"].corr(aligned["local"])),
        "normalized_nav_max_deviation": float(diff.abs().max()),
        "daily_return_correlation": float(ret_aligned["qc"].corr(ret_aligned["local"])) if len(ret_aligned) > 1 else float("nan"),
        "first_max_divergence_date": str(first_div_idx.date()),
        "orders_provided": qc_orders is not None and not qc_orders.empty,
    }
    if result["nav_correlation"] < 0.99:
        result["status"] = "DIVERGENT"
    return result
