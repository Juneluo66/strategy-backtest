"""Pre-registered stability checks — no parameter search."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .backtest import run_weight_schedule
from .bootstrap import block_bootstrap_cagr_diff
from .metrics import rich_metrics
from .signals import build_monthly_targets


def _slice_equity(equity: pd.DataFrame, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
    out = equity
    if start:
        out = out.loc[out.index >= pd.Timestamp(start)]
    if end:
        out = out.loc[out.index <= pd.Timestamp(end)]
    return out


def _metrics_from_run(
    run: dict,
    spy: pd.Series,
    qqq: pd.Series,
    ew: pd.Series,
    rf: pd.Series,
    rf_meta: dict,
    crisis: dict,
) -> dict:
    return rich_metrics(
        run["equity"],
        run["trades"],
        spy=spy,
        qqq=qqq,
        equal_weight=ew,
        rf=rf,
        rf_meta=rf_meta,
        crisis_windows=crisis,
    )


def run_stability(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    sectors: list[str],
    *,
    spy_ret: pd.Series,
    qqq_ret: pd.Series,
    ew_ret: pd.Series,
    rf: pd.Series,
    rf_meta: dict,
    crisis_windows: dict,
    one_way_bps: float = 5.0,
    versions: Optional[list[str]] = None,
    stability_cfg: Optional[dict] = None,
) -> dict:
    versions = versions or [
        "base_12_1_top3",
        "composite_6_1_12_1_top3",
        "composite_top3_buffer",
    ]
    cfg = stability_cfg or {}
    results: dict = {
        "versions": {},
        "rolling": [],
        "leave_one_out": [],
        "segment": [],
        "bootstrap": [],
        "fixed_endpoints": [],
    }

    def _run_version(version: str, pool: list[str], **bt_kwargs) -> dict:
        targets = build_monthly_targets(closes, pool, version)
        return run_weight_schedule(
            opens,
            closes,
            targets,
            symbols=pool,
            **bt_kwargs,
        )

    cutoffs = list(
        cfg.get(
            "fixed_cutoffs",
            [
                "2005-12-31",
                "2008-12-31",
                "2012-12-31",
                "2016-12-31",
                "2020-12-31",
                "2024-12-31",
                "latest",
            ],
        )
    )
    restarts = list(cfg.get("restart_from", ["2003-01-01", "2008-01-01", "2013-01-01"]))
    exclude_years = list(cfg.get("exclude_last_years", [1, 2, 3]))
    rolling_years = list(cfg.get("rolling_years", [3, 5, 10]))
    boot_cfg = cfg.get("block_bootstrap", {})
    n_boot = int(boot_cfg.get("n_boot", 400))
    block = int(boot_cfg.get("block_trading_days", 21))
    seed = int(boot_cfg.get("seed", 42))

    segments = {
        "2000_2002": ("2000-01-01", "2002-12-31"),
        "2008": ("2008-01-01", "2008-12-31"),
        "2020": ("2020-01-01", "2020-12-31"),
        "2022": ("2022-01-01", "2022-12-31"),
    }

    for version in versions:
        block_out: dict = {}
        base = _run_version(version, sectors, one_way_bps=one_way_bps, execution_delay_sessions=1)
        block_out["baseline"] = _metrics_from_run(
            base, spy_ret, qqq_ret, ew_ret, rf, rf_meta, crisis_windows
        )

        for bps in (10.0, 20.0):
            run = _run_version(version, sectors, one_way_bps=bps, execution_delay_sessions=1)
            block_out[f"cost_{int(bps)}bp"] = _metrics_from_run(
                run, spy_ret, qqq_ret, ew_ret, rf, rf_meta, crisis_windows
            )

        delay2 = _run_version(version, sectors, one_way_bps=one_way_bps, execution_delay_sessions=2)
        block_out["extra_delay"] = _metrics_from_run(
            delay2, spy_ret, qqq_ret, ew_ret, rf, rf_meta, crisis_windows
        )

        eq = base["equity"]
        end = eq.index.max()
        for n in exclude_years:
            cut = end - pd.DateOffset(years=n)
            sliced = _slice_equity(eq, end=str(cut.date()))
            tr = base["trades"]
            if not tr.empty:
                tr = tr[tr["date"] <= cut]
            block_out[f"exclude_last_{n}y"] = rich_metrics(
                sliced,
                tr,
                spy=spy_ret,
                qqq=qqq_ret,
                equal_weight=ew_ret,
                rf=rf,
                rf_meta=rf_meta,
                crisis_windows=crisis_windows,
            )

        for start in restarts:
            restart = _slice_equity(eq, start=start)
            tr = base["trades"]
            if not tr.empty:
                tr = tr[tr["date"] >= pd.Timestamp(start)]
            key = f"restart_{start[:4]}"
            block_out[key] = rich_metrics(
                restart,
                tr,
                spy=spy_ret,
                qqq=qqq_ret,
                equal_weight=ew_ret,
                rf=rf,
                rf_meta=rf_meta,
                crisis_windows=crisis_windows,
            )

        block_out["fixed_cutoffs"] = {}
        for cut in cutoffs:
            if cut == "latest":
                sl = eq
                trs = base["trades"]
            else:
                sl = _slice_equity(eq, end=cut)
                trs = base["trades"]
                if not trs.empty:
                    trs = trs[trs["date"] <= pd.Timestamp(cut)]
            m = rich_metrics(
                sl,
                trs,
                spy=spy_ret,
                qqq=qqq_ret,
                equal_weight=ew_ret,
                rf=rf,
                rf_meta=rf_meta,
                crisis_windows=crisis_windows,
            )
            block_out["fixed_cutoffs"][cut] = m
            # SPY CAGR on same window for endpoint table
            spy_sl = spy_ret.reindex(sl.index).dropna()
            if len(spy_sl) > 5:
                spy_eq = (1 + spy_sl).cumprod()
                y = max((spy_eq.index.max() - spy_eq.index.min()).days / 365.25, 1 / 12)
                spy_cagr = float(spy_eq.iloc[-1] ** (1 / y) - 1)
                spy_wealth = float(spy_eq.iloc[-1])
            else:
                spy_cagr = spy_wealth = np.nan
            results["fixed_endpoints"].append(
                {
                    "version": version,
                    "cutoff": cut,
                    "strategy_cagr": m.get("cagr"),
                    "strategy_final_wealth": m.get("final_wealth"),
                    "spy_cagr": spy_cagr,
                    "spy_final_wealth": spy_wealth,
                    "beats_spy_cagr": bool(
                        pd.notna(m.get("cagr")) and pd.notna(spy_cagr) and m["cagr"] > spy_cagr
                    ),
                    "beats_spy_wealth": bool(
                        pd.notna(m.get("final_wealth"))
                        and pd.notna(spy_wealth)
                        and m["final_wealth"] > spy_wealth
                    ),
                }
            )

        for seg_name, (s0, s1) in segments.items():
            sl = _slice_equity(eq, start=s0, end=s1)
            trs = base["trades"]
            if not trs.empty:
                trs = trs[(trs["date"] >= pd.Timestamp(s0)) & (trs["date"] <= pd.Timestamp(s1))]
            m = rich_metrics(
                sl,
                trs,
                spy=spy_ret,
                qqq=qqq_ret,
                equal_weight=ew_ret,
                rf=rf,
                rf_meta=rf_meta,
                crisis_windows=crisis_windows,
            )
            block_out[f"segment_{seg_name}"] = m
            results["segment"].append({"version": version, "segment": seg_name, **{
                k: m.get(k) for k in ("cagr", "final_wealth", "max_drawdown", "sharpe")
            }})

        results["versions"][version] = block_out

        # Rolling windows vs SPY
        net = eq["net_return"]
        for win_years in rolling_years:
            span = int(252 * win_years)
            if len(net) < span:
                continue
            for i in range(0, len(net) - span + 1, 21):
                window = net.iloc[i : i + span]
                equity = (1 + window).cumprod()
                cagr = float(equity.iloc[-1] ** (1 / win_years) - 1)
                spy_w = spy_ret.reindex(window.index).dropna()
                if len(spy_w) < span * 0.9:
                    continue
                spy_eq = (1 + spy_w).cumprod()
                y = max((spy_eq.index.max() - spy_eq.index.min()).days / 365.25, 1 / 12)
                spy_cagr = float(spy_eq.iloc[-1] ** (1 / y) - 1) if y > 0 else np.nan
                results["rolling"].append(
                    {
                        "version": version,
                        "window_years": win_years,
                        "start": str(window.index[0].date()),
                        "end": str(window.index[-1].date()),
                        "cagr": cagr,
                        "spy_cagr": spy_cagr,
                        "beats_spy": bool(pd.notna(cagr) and pd.notna(spy_cagr) and cagr > spy_cagr),
                        "max_drawdown": float((equity / equity.cummax() - 1).min()),
                    }
                )

        # Block bootstrap CAGR diff vs SPY
        boot = block_bootstrap_cagr_diff(
            net, spy_ret, n_boot=n_boot, block=block, seed=seed
        )
        boot["version"] = version
        results["bootstrap"].append(boot)

    # Leave-one-sector-out (non-XLK drops + full LOO for completeness)
    for drop in sectors:
        pool = [s for s in sectors if s != drop]
        for version in versions:
            run = _run_version(version, pool, one_way_bps=one_way_bps, execution_delay_sessions=1)
            m = _metrics_from_run(run, spy_ret, qqq_ret, ew_ret, rf, rf_meta, crisis_windows)
            results["leave_one_out"].append(
                {
                    "version": version,
                    "dropped": drop,
                    "cagr": m.get("cagr"),
                    "final_wealth": m.get("final_wealth"),
                    "sharpe": m.get("sharpe"),
                    "max_drawdown": m.get("max_drawdown"),
                    "rel_spy_relative_cagr": m.get("rel_spy_relative_cagr"),
                }
            )

    return results
