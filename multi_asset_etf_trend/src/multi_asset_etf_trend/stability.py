"""Pre-registered stability checks — no parameter search."""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pandas as pd

from .backtest import monthly_rebalance_fixed, run_weight_schedule
from .metrics import rich_metrics
from .signals import build_monthly_targets


def _slice_equity(equity: pd.DataFrame, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
    out = equity
    if start:
        out = out.loc[out.index >= pd.Timestamp(start)]
    if end:
        out = out.loc[out.index <= pd.Timestamp(end)]
    return out


def _metrics_from_run(run: dict, spy: pd.Series, sixty: pd.Series, bil: pd.Series, crisis: dict) -> dict:
    return rich_metrics(
        run["equity"],
        run["trades"],
        spy=spy,
        sixty_forty=sixty,
        bil=bil,
        crisis_windows=crisis,
    )


def run_stability(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    risk: list[str],
    cash: str,
    *,
    spy_ret: pd.Series,
    sixty_ret: pd.Series,
    bil_ret: pd.Series,
    crisis_windows: dict,
    one_way_bps: float = 5.0,
    vol_lookback: int = 63,
) -> dict:
    """All pre-registered stability experiments for the three versions."""
    versions = ["base_12m_equal", "ensemble_equal", "ensemble_risk_balanced"]
    results: dict = {"versions": {}, "rolling": [], "leave_one_out": [], "asset_contrib": []}

    def _run_version(version: str, risk_pool: list[str], **bt_kwargs) -> dict:
        targets = build_monthly_targets(
            closes, risk_pool, cash, version, vol_lookback=vol_lookback
        )
        return run_weight_schedule(
            opens,
            closes,
            targets,
            symbols=risk_pool + [cash],
            **bt_kwargs,
        )

    # Baseline + cost double + delay
    for version in versions:
        block: dict = {}
        base = _run_version(version, risk, one_way_bps=one_way_bps, execution_delay_sessions=1)
        block["baseline"] = _metrics_from_run(base, spy_ret, sixty_ret, bil_ret, crisis_windows)

        cost10 = _run_version(version, risk, one_way_bps=10.0, execution_delay_sessions=1)
        block["cost_10bp"] = _metrics_from_run(cost10, spy_ret, sixty_ret, bil_ret, crisis_windows)

        delay2 = _run_version(version, risk, one_way_bps=one_way_bps, execution_delay_sessions=2)
        block["extra_delay"] = _metrics_from_run(delay2, spy_ret, sixty_ret, bil_ret, crisis_windows)

        eq = base["equity"]
        end = eq.index.max()
        for n in (1, 2):
            cut = end - pd.DateOffset(years=n)
            sliced = _slice_equity(eq, end=str(cut.date()))
            # Rebuild trades filtered
            tr = base["trades"]
            if not tr.empty:
                tr = tr[tr["date"] <= cut]
            block[f"exclude_last_{n}y"] = rich_metrics(
                sliced, tr, spy=spy_ret, sixty_forty=sixty_ret, bil=bil_ret, crisis_windows=crisis_windows
            )

        restart = _slice_equity(eq, start="2010-01-01")
        tr = base["trades"]
        if not tr.empty:
            tr = tr[tr["date"] >= pd.Timestamp("2010-01-01")]
        block["restart_2010"] = rich_metrics(
            restart, tr, spy=spy_ret, sixty_forty=sixty_ret, bil=bil_ret, crisis_windows=crisis_windows
        )

        # Fixed cutoffs
        cutoffs = ["2015-12-31", "2018-12-31", "2020-12-31", "2022-12-31", "2024-12-31", "latest"]
        block["fixed_cutoffs"] = {}
        for cut in cutoffs:
            if cut == "latest":
                sl = eq
                trs = base["trades"]
            else:
                sl = _slice_equity(eq, end=cut)
                trs = base["trades"]
                if not trs.empty:
                    trs = trs[trs["date"] <= pd.Timestamp(cut)]
            block["fixed_cutoffs"][cut] = rich_metrics(
                sl, trs, spy=spy_ret, sixty_forty=sixty_ret, bil=bil_ret, crisis_windows=crisis_windows
            )

        # Post-2008 subsample (challenger vs base attribution)
        post2009 = _slice_equity(eq, start="2009-04-01")
        trs = base["trades"]
        if not trs.empty:
            trs = trs[trs["date"] >= pd.Timestamp("2009-04-01")]
        block["post_2008"] = rich_metrics(
            post2009, trs, spy=spy_ret, sixty_forty=sixty_ret, bil=bil_ret, crisis_windows=crisis_windows
        )

        results["versions"][version] = block

        # Rolling 3y / 5y windows on daily equity (lightweight stats only)
        net = eq["net_return"]
        for win_years in (3, 5):
            span = int(252 * win_years)
            if len(net) < span:
                continue
            for i in range(0, len(net) - span + 1, 21):  # ~monthly steps
                window = net.iloc[i : i + span]
                years = win_years
                equity = (1 + window).cumprod()
                cagr = float(equity.iloc[-1] ** (1 / years) - 1)
                vol = float(window.std(ddof=1) * np.sqrt(252)) if len(window) > 1 else np.nan
                sharpe = (
                    float(window.mean() / window.std(ddof=1) * np.sqrt(252))
                    if len(window) > 1 and window.std(ddof=1)
                    else np.nan
                )
                max_dd = float((equity / equity.cummax() - 1).min())
                bil_col = "w_bil" if "w_bil" in eq.columns else None
                avg_bil = float(eq[bil_col].iloc[i : i + span].mean()) if bil_col else np.nan
                results["rolling"].append(
                    {
                        "version": version,
                        "window_years": win_years,
                        "start": str(window.index[0].date()),
                        "end": str(window.index[-1].date()),
                        "cagr": cagr,
                        "sharpe": sharpe,
                        "volatility": vol,
                        "max_drawdown": max_dd,
                        "avg_bil_weight": avg_bil,
                    }
                )

    # Leave-one-asset-out on challenger + baselines
    for drop in risk:
        pool = [s for s in risk if s != drop]
        for version in versions:
            run = _run_version(version, pool, one_way_bps=one_way_bps, execution_delay_sessions=1)
            m = _metrics_from_run(run, spy_ret, sixty_ret, bil_ret, crisis_windows)
            results["leave_one_out"].append(
                {
                    "version": version,
                    "dropped": drop,
                    "cagr": m.get("cagr"),
                    "sharpe": m.get("sharpe"),
                    "max_drawdown": m.get("max_drawdown"),
                    "avg_bil_weight": m.get("avg_bil_weight"),
                }
            )

    return results


def asset_group_contributions(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    risk: list[str],
    cash: str,
    groups: dict[str, list[str]],
    version: str = "ensemble_risk_balanced",
    *,
    one_way_bps: float = 5.0,
    vol_lookback: int = 63,
) -> pd.DataFrame:
    """
    Approximate group contribution via leave-group-out wealth gap vs full portfolio.

    contribution_cagr ≈ full_cagr - leave_group_out_cagr
    maxdd_relief ≈ full_maxdd - leave_group_out_maxdd
      (positive ⇒ group made drawdowns shallower / helped protection)
    """
    full_targets = build_monthly_targets(closes, risk, cash, version, vol_lookback=vol_lookback)
    full = run_weight_schedule(
        opens, closes, full_targets, one_way_bps=one_way_bps, symbols=risk + [cash]
    )
    full_eq = (1 + full["equity"]["net_return"]).cumprod()
    years = max((full_eq.index.max() - full_eq.index.min()).days / 365.25, 1 / 12)
    full_cagr = float(full_eq.iloc[-1] ** (1 / years) - 1)
    full_dd = float((full_eq / full_eq.cummax() - 1).min())

    rows = []
    for gname, members in groups.items():
        pool = [s for s in risk if s not in members]
        if not pool:
            continue
        targets = build_monthly_targets(closes, pool, cash, version, vol_lookback=vol_lookback)
        run = run_weight_schedule(
            opens, closes, targets, one_way_bps=one_way_bps, symbols=pool + [cash]
        )
        eq = (1 + run["equity"]["net_return"]).cumprod()
        y = max((eq.index.max() - eq.index.min()).days / 365.25, 1 / 12)
        cagr = float(eq.iloc[-1] ** (1 / y) - 1)
        dd = float((eq / eq.cummax() - 1).min())
        rows.append(
            {
                "version": version,
                "group": gname,
                "members": ",".join(members),
                "full_cagr": full_cagr,
                "loo_cagr": cagr,
                "cagr_contribution": full_cagr - cagr,
                "full_max_drawdown": full_dd,
                "loo_max_drawdown": dd,
                "maxdd_relief": full_dd - dd,
            }
        )
    return pd.DataFrame(rows)
