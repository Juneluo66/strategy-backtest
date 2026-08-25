"""Branch-level attribution for conditional_leveraged_etf_rotation."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def branch_attribution(equity: pd.DataFrame, signal_log: pd.DataFrame) -> pd.DataFrame:
    """Attribute daily returns to terminal branch and target."""
    if signal_log.empty or equity.empty:
        return pd.DataFrame()

    log = signal_log.set_index("date")
    merged = equity.join(log[["target", "branch_path", "market_regime"]], how="inner")
    merged["branch_key"] = merged["branch_path"]

    rows: list[dict] = []
    for branch, grp in merged.groupby("branch_key"):
        rets = grp["net_return"]
        target = grp["target"].iloc[0]
        rows.append(
            {
                "branch": branch,
                "terminal_target": target,
                "days": len(grp),
                "pct_time": len(grp) / len(merged),
                "cagr_contribution_approx": _segment_cagr(rets),
                "pnl_contribution": float(rets.sum()),
                "avg_daily_return": float(rets.mean()),
                "win_rate": float((rets > 0).mean()),
                "volatility": float(rets.std(ddof=1) * np.sqrt(252)) if len(rets) > 1 else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("pnl_contribution", ascending=False)


def target_attribution_summary(signal_log: pd.DataFrame) -> pd.DataFrame:
    """Time spent per target asset."""
    if signal_log.empty:
        return pd.DataFrame()
    counts = signal_log["target"].value_counts()
    total = len(signal_log)
    return pd.DataFrame(
        {
            "target": counts.index,
            "days": counts.values,
            "pct_time": counts.values / total,
        }
    )


def uvxy_branch_stats(signal_log: pd.DataFrame, equity: pd.DataFrame, trades: pd.DataFrame) -> dict[str, Any]:
    """Detailed UVXY branch statistics."""
    if signal_log.empty:
        return {}
    uvxy_days = signal_log[signal_log["target"] == "UVXY"]
    entries = int((signal_log["target"] == "UVXY").sum())
    # Holding periods from trades
    periods: list[int] = []
    if not trades.empty:
        t = trades.sort_values("date")
        current_start = None
        for _, row in t.iterrows():
            if row["side"] == "buy" and row["ticker"] == "UVXY":
                current_start = pd.Timestamp(row["date"])
            elif row["side"] == "sell" and row["ticker"] == "UVXY" and current_start:
                periods.append((pd.Timestamp(row["date"]) - current_start).days)
                current_start = None

    uvxy_rets = equity.join(signal_log.set_index("date")[["target"]], how="inner")
    uvxy_rets = uvxy_rets[uvxy_rets["target"] == "UVXY"]["net_return"]

    return {
        "uvxy_entry_signals": entries,
        "uvxy_days_held": int(len(uvxy_days)),
        "pct_portfolio_time": len(uvxy_days) / len(signal_log),
        "median_holding_days": float(np.median(periods)) if periods else float("nan"),
        "avg_holding_days": float(np.mean(periods)) if periods else float("nan"),
        "total_pnl_proxy": float(uvxy_rets.sum()),
        "avg_daily_return_in_uvxy": float(uvxy_rets.mean()) if len(uvxy_rets) else float("nan"),
        "win_rate_in_uvxy": float((uvxy_rets > 0).mean()) if len(uvxy_rets) else float("nan"),
    }


def _segment_cagr(rets: pd.Series) -> float:
    r = rets.dropna()
    if r.empty:
        return float("nan")
    years = len(r) / 252
    if years <= 0:
        return float("nan")
    return float((1 + r).prod() ** (1 / years) - 1)
