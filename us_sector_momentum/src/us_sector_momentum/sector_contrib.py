"""Sector holding months, contribution, and XLK concentration audit."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .backtest import run_weight_schedule
from .metrics import rich_metrics
from .signals import build_monthly_targets


def _holding_month_share(targets: pd.DataFrame, sectors: list[str]) -> pd.DataFrame:
    if targets.empty:
        return pd.DataFrame(columns=["sector", "hold_months", "hold_month_share"])
    # One row per signal_date × symbol with weight>0
    held = targets[targets["weight"] > 1e-12].copy()
    months = held.groupby("symbol")["signal_date"].nunique()
    n_signals = held["signal_date"].nunique()
    rows = []
    for s in sectors:
        hm = int(months.get(s, 0))
        rows.append(
            {
                "sector": s,
                "hold_months": hm,
                "hold_month_share": hm / n_signals if n_signals else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _approx_contribution_from_weights(equity: pd.DataFrame, sectors: list[str], closes: pd.DataFrame) -> pd.DataFrame:
    """
    Daily contribution ≈ weight_{t-1} * asset_return_t, aggregated to cumulative log-ish wealth gap proxy.
    Uses close-to-close asset returns aligned to equity index.
    """
    if equity.empty:
        return pd.DataFrame(columns=["sector", "cum_contribution", "contribution_share"])
    rets = closes[sectors].pct_change(fill_method=None).reindex(equity.index)
    contrib = {}
    for s in sectors:
        wcol = f"w_{s}"
        if wcol not in equity.columns:
            contrib[s] = 0.0
            continue
        w = equity[wcol].shift(1).fillna(0.0)
        piece = (w * rets[s]).fillna(0.0)
        contrib[s] = float(piece.sum())
    total = sum(abs(v) for v in contrib.values()) or 1.0
    # Also signed share of positive sum for excess attribution context
    pos = sum(v for v in contrib.values() if v > 0) or 1.0
    rows = []
    for s in sectors:
        rows.append(
            {
                "sector": s,
                "cum_contribution": contrib[s],
                "contribution_share_abs": abs(contrib[s]) / total,
                "contribution_share_of_positive": max(contrib[s], 0.0) / pos,
            }
        )
    return pd.DataFrame(rows)


def sector_contribution_audit(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    sectors: list[str],
    version: str,
    *,
    one_way_bps: float = 5.0,
    spy_ret: Optional[pd.Series] = None,
    qqq_ret: Optional[pd.Series] = None,
    ew_ret: Optional[pd.Series] = None,
    rf: Optional[pd.Series] = None,
    rf_meta: Optional[dict] = None,
) -> dict:
    targets = build_monthly_targets(closes, sectors, version)
    run = run_weight_schedule(
        opens, closes, targets, one_way_bps=one_way_bps, symbols=sectors
    )
    hold = _holding_month_share(run["targets"], sectors)
    contrib = _approx_contribution_from_weights(run["equity"], sectors, closes)
    merged = hold.merge(contrib, on="sector", how="outer")
    merged["version"] = version

    # Full vs exclude XLK
    full_m = rich_metrics(
        run["equity"],
        run["trades"],
        spy=spy_ret if spy_ret is not None else closes.get("SPY", pd.Series(dtype=float)),
        qqq=qqq_ret,
        equal_weight=ew_ret,
        rf=rf,
        rf_meta=rf_meta,
    )
    pool_no_xlk = [s for s in sectors if s != "XLK"]
    targets_no = build_monthly_targets(closes, pool_no_xlk, version)
    run_no = run_weight_schedule(
        opens, closes, targets_no, one_way_bps=one_way_bps, symbols=pool_no_xlk
    )
    no_m = rich_metrics(
        run_no["equity"],
        run_no["trades"],
        spy=spy_ret if spy_ret is not None else closes.get("SPY", pd.Series(dtype=float)),
        qqq=qqq_ret,
        equal_weight=ew_ret,
        rf=rf,
        rf_meta=rf_meta,
    )

    # XLK held vs not-held months (based on target weights > 0)
    eq = run["equity"]
    if "w_XLK" in eq.columns and not eq.empty:
        has_xlk = eq["w_XLK"] > 1e-12
        r_with = eq.loc[has_xlk, "net_return"]
        r_without = eq.loc[~has_xlk, "net_return"]

        def _ann(r: pd.Series) -> float:
            if len(r) < 5:
                return float("nan")
            y = max((r.index.max() - r.index.min()).days / 365.25, 1 / 12)
            return float((1 + r).prod() ** (1 / y) - 1)

        with_cagr = _ann(r_with)
        without_cagr = _ann(r_without)
        share_days_xlk = float(has_xlk.mean())
    else:
        with_cagr = without_cagr = share_days_xlk = np.nan

    spy_cagr = full_m.get("cagr")
    # Excess vs SPY approximation for XLK share of excess
    full_excess = (full_m.get("cagr") or np.nan) - (full_m.get("rel_spy_relative_cagr") is not None and (
        # use relative cagr as excess proxy when available
        full_m.get("rel_spy_relative_cagr")
    ) or np.nan)
    # Cleaner: excess_cagr ≈ strategy_cagr - spy_cagr from Metric C relative approx
    # Reconstruct spy cagr from final relative nav if needed
    if spy_ret is not None and not run["equity"].empty:
        net = run["equity"]["net_return"]
        spy_a = spy_ret.reindex(net.index).dropna()
        if len(spy_a) > 5:
            y = max((spy_a.index.max() - spy_a.index.min()).days / 365.25, 1 / 12)
            spy_cagr = float((1 + spy_a).prod() ** (1 / y) - 1)
    excess_full = (full_m.get("cagr") - spy_cagr) if pd.notna(full_m.get("cagr")) and pd.notna(spy_cagr) else np.nan
    excess_no = (no_m.get("cagr") - spy_cagr) if pd.notna(no_m.get("cagr")) and pd.notna(spy_cagr) else np.nan
    xlk_excess_gap = (
        excess_full - excess_no if pd.notna(excess_full) and pd.notna(excess_no) else np.nan
    )
    xlk_share_of_excess = (
        xlk_excess_gap / excess_full
        if pd.notna(xlk_excess_gap) and pd.notna(excess_full) and abs(excess_full) > 1e-8
        else np.nan
    )

    xlk_row = merged.loc[merged["sector"] == "XLK"]
    xlk_hold_share = float(xlk_row["hold_month_share"].iloc[0]) if len(xlk_row) else np.nan
    xlk_contrib_share = (
        float(xlk_row["contribution_share_of_positive"].iloc[0]) if len(xlk_row) else np.nan
    )

    summary = {
        "version": version,
        "full_cagr": full_m.get("cagr"),
        "full_final_wealth": full_m.get("final_wealth"),
        "exclude_xlk_cagr": no_m.get("cagr"),
        "exclude_xlk_final_wealth": no_m.get("final_wealth"),
        "spy_cagr": spy_cagr,
        "excess_cagr_vs_spy": excess_full,
        "excess_cagr_vs_spy_ex_xlk": excess_no,
        "xlk_share_of_excess_cagr": xlk_share_of_excess,
        "xlk_hold_month_share": xlk_hold_share,
        "xlk_contribution_share_of_positive": xlk_contrib_share,
        "cagr_when_holding_xlk": with_cagr,
        "cagr_when_not_holding_xlk": without_cagr,
        "day_share_holding_xlk": share_days_xlk,
        "beta_spy": full_m.get("beta_spy"),
        "beta_qqq": full_m.get("beta_qqq"),
        "rel_qqq_final_relative_nav": full_m.get("rel_qqq_final_relative_nav"),
        "rel_qqq_relative_cagr": full_m.get("rel_qqq_relative_cagr"),
        "note": (
            "Long-run overweight of XLK must not be labeled sector-momentum alpha; "
            "disclose XLK dependence explicitly."
        ),
    }
    return {
        "contributions": merged,
        "summary": summary,
        "full_metrics": full_m,
        "exclude_xlk_metrics": no_m,
        "run": run,
        "run_exclude_xlk": run_no,
    }
