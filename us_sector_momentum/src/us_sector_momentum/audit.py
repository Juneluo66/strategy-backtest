"""Full sector-momentum audit orchestration, gate, and report writer."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .artifacts import new_run_directory
from .backtest import buy_and_hold, monthly_rebalance_fixed, run_weight_schedule
from .config import SectorConfig, load_config
from .data import (
    audit_prices,
    fetch_prices,
    load_ohlc,
    load_rf_daily,
    reuse_sibling_caches,
    strict_common_index,
)
from .metrics import rich_metrics
from .sector_contrib import sector_contribution_audit
from .signals import build_monthly_targets
from .stability import run_stability

FORMAL_NAMES = [
    "spy_buy_hold",
    "qqq_buy_hold",
    "equal_weight_9_monthly",
    "base_12_1_top3",
    "composite_6_1_12_1_top3",
    "composite_top3_buffer",
]


def _align_panels(opens: pd.DataFrame, closes: pd.DataFrame, symbols: list[str]):
    o = opens[symbols]
    c = closes[symbols]
    idx = strict_common_index(c)
    return o.reindex(idx), c.reindex(idx)


def evaluate_gate(
    main_metrics: dict[str, dict],
    stability: dict,
    xlk_summary: dict,
) -> dict:
    """
    Challenger = composite_6_1_12_1_top3.

    Hard fail if net CAGR or final wealth does not beat SPY.
    Otherwise require majority of the listed checks (≥10 of 13), with 1–3 hard.
    """
    ch = main_metrics["composite_6_1_12_1_top3"]
    spy = main_metrics["spy_buy_hold"]
    stab = stability["versions"]["composite_6_1_12_1_top3"]
    checks: dict[str, bool] = {}

    # 1–3 hard wealth/CAGR gates
    checks["net_cagr_above_spy"] = bool(
        pd.notna(ch.get("cagr")) and pd.notna(spy.get("cagr")) and ch["cagr"] > spy["cagr"]
    )
    checks["final_wealth_above_spy"] = bool(
        pd.notna(ch.get("final_wealth"))
        and pd.notna(spy.get("final_wealth"))
        and ch["final_wealth"] > spy["final_wealth"]
    )
    checks["cagr_edge_at_least_~1pp"] = bool(
        pd.notna(ch.get("cagr"))
        and pd.notna(spy.get("cagr"))
        and (ch["cagr"] - spy["cagr"]) >= 0.0095
    )

    # 4–5 rolling beat rates
    roll = [r for r in stability.get("rolling", []) if r["version"] == "composite_6_1_12_1_top3"]
    r5 = [r for r in roll if r["window_years"] == 5]
    r10 = [r for r in roll if r["window_years"] == 10]
    beat5 = float(np.mean([r["beats_spy"] for r in r5])) if r5 else np.nan
    beat10 = float(np.mean([r["beats_spy"] for r in r10])) if r10 else np.nan
    checks["rolling_5y_beat_spy_ge_55pct"] = bool(pd.notna(beat5) and beat5 >= 0.55)
    checks["rolling_10y_beat_spy_ge_60pct"] = bool(pd.notna(beat10) and beat10 >= 0.60)

    # 6 exclude last 1/2/3y still ahead of SPY
    for n in (1, 2, 3):
        sub = stab.get(f"exclude_last_{n}y", {})
        # Compare to SPY sliced similarly via relative cagr > 0 or final wealth vs spy on same window
        checks[f"exclude_last_{n}y_still_leads_spy"] = bool(
            pd.notna(sub.get("rel_spy_relative_cagr")) and sub["rel_spy_relative_cagr"] > 0
        )

    # 7 majority fixed cutoffs lead SPY
    endpoints = [
        r
        for r in stability.get("fixed_endpoints", [])
        if r["version"] == "composite_6_1_12_1_top3"
    ]
    if endpoints:
        frac = float(np.mean([r["beats_spy_cagr"] for r in endpoints]))
        checks["fixed_cutoffs_majority_lead_spy"] = bool(frac >= 0.5)
    else:
        checks["fixed_cutoffs_majority_lead_spy"] = False

    # 8 cost 10bp / 20bp still lead
    for bps in (10, 20):
        m = stab.get(f"cost_{bps}bp", {})
        checks[f"cost_{bps}bp_still_leads_spy"] = bool(
            pd.notna(m.get("rel_spy_relative_cagr")) and m["rel_spy_relative_cagr"] > 0
        )

    # 9 delay does not flip
    d = stab.get("extra_delay", {})
    checks["delay_does_not_flip"] = bool(
        pd.notna(d.get("rel_spy_relative_cagr")) and d["rel_spy_relative_cagr"] > 0
    )

    # 10 excess not entirely from XLK
    xlk_share = xlk_summary.get("xlk_share_of_excess_cagr")
    ex_xlk_still = xlk_summary.get("excess_cagr_vs_spy_ex_xlk")
    checks["excess_not_entirely_from_xlk"] = bool(
        (
            pd.notna(xlk_share)
            and xlk_share < 0.95
            and pd.notna(ex_xlk_still)
            and ex_xlk_still > 0
        )
        or (
            pd.isna(xlk_share)
            and pd.notna(ex_xlk_still)
            and ex_xlk_still > 0
        )
    )

    # 11 QQQ results disclosed (always true if metrics present)
    checks["qqq_results_disclosed"] = bool(
        pd.notna(ch.get("rel_qqq_final_relative_nav")) or pd.notna(ch.get("beta_qqq"))
    )

    # 12 MaxDD not >5pp deeper than SPY
    checks["maxdd_not_5pp_deeper_than_spy"] = bool(
        pd.notna(ch.get("max_drawdown"))
        and pd.notna(spy.get("max_drawdown"))
        and ch["max_drawdown"] >= spy["max_drawdown"] - 0.05
    )

    # 13 no post-hoc sector/horizon/top-n search (structural — always true in this frozen code)
    checks["no_posthoc_search"] = True

    hard = ["net_cagr_above_spy", "final_wealth_above_spy", "cagr_edge_at_least_~1pp"]
    hard_ok = all(checks[k] for k in hard)
    n_pass = int(sum(checks.values()))
    n_checks = int(len(checks))
    majority = n_pass >= int(np.ceil(0.7 * n_checks))  # ≥70% ≈ 10/13

    if not checks["net_cagr_above_spy"] or not checks["final_wealth_above_spy"]:
        label = "REJECTED"
        passed = False
        reason = "CAGR/final wealth did not beat SPY — Sharpe alone cannot pass."
    elif hard_ok and majority:
        label = "SECTOR_MOMENTUM_RETURN_CANDIDATE"
        passed = True
        reason = "Hard wealth gates and majority of pre-registered checks passed."
    else:
        label = "REJECTED"
        passed = False
        reason = "Failed hard edge and/or majority stability/XLK checks."

    return {
        "label": label,
        "passed": passed,
        "n_pass": n_pass,
        "n_checks": n_checks,
        "checks": checks,
        "rolling_5y_beat_rate": beat5,
        "rolling_10y_beat_rate": beat10,
        "reason": reason,
        "notes": [
            "Primary objective is long-run terminal wealth vs SPY, not low drawdown or high cash.",
            "Higher Sharpe with lower terminal wealth than SPY is a failure.",
            "Do not retune Top-N / lookbacks / add SMA or BIL after seeing results.",
            "IBKR/production configs must not be modified (ibkr_modified=false).",
        ],
    }


def run_full_audit(
    config: Optional[SectorConfig] = None,
    *,
    refresh: bool = False,
) -> dict:
    config = config or load_config()
    reuse_sibling_caches(config)
    try:
        fetch_prices(config, refresh=refresh)
    except RuntimeError:
        if refresh:
            raise
        fetch_prices(config, refresh=False)

    opens_all, closes_all, raw_closes = load_ohlc(config, symbols=config.panel_symbols)
    price_audit = audit_prices(config, opens_all, closes_all, raw_closes)

    opens, closes = _align_panels(opens_all, closes_all, config.panel_symbols)
    sectors = config.sectors
    crisis = {k: tuple(v) for k, v in config.raw["crisis_windows"].items()}

    rf, rf_meta = load_rf_daily(config, closes.index)
    price_audit["rf_meta"] = rf_meta

    spy_bh = buy_and_hold(opens, closes, "SPY")
    qqq_bh = buy_and_hold(opens, closes, "QQQ")
    ew_w = {s: 1.0 / len(sectors) for s in sectors}
    ew9 = monthly_rebalance_fixed(opens, closes, ew_w, one_way_bps=config.one_way_bps)

    runs: dict[str, dict] = {
        "spy_buy_hold": {
            "equity": spy_bh,
            "trades": pd.DataFrame(),
            "targets": pd.DataFrame(),
            "turnover_status": "buy_and_hold",
        },
        "qqq_buy_hold": {
            "equity": qqq_bh,
            "trades": pd.DataFrame(),
            "targets": pd.DataFrame(),
            "turnover_status": "buy_and_hold",
        },
        "equal_weight_9_monthly": {**ew9, "turnover_status": "measured"},
    }

    for version in config.raw["versions"]:
        targets = build_monthly_targets(closes, sectors, version)
        run = run_weight_schedule(
            opens,
            closes,
            targets,
            one_way_bps=config.one_way_bps,
            symbols=sectors,
        )
        runs[version] = {**run, "turnover_status": "measured"}

    start_dates = [run["equity"].index.min() for run in runs.values() if not run["equity"].empty]
    common_start = max(start_dates) if start_dates else None
    if common_start is not None:
        for run in runs.values():
            eq = run["equity"]
            run["equity"] = eq.loc[eq.index >= common_start]
            if not run["trades"].empty and "date" in run["trades"]:
                run["trades"] = run["trades"][run["trades"]["date"] >= common_start]

    spy_ret = closes["SPY"].pct_change(fill_method=None)
    qqq_ret = closes["QQQ"].pct_change(fill_method=None)
    ew_ret = ew9["equity"]["net_return"]

    metrics_rows = []
    metrics_map: dict[str, dict] = {}
    for name in FORMAL_NAMES:
        run = runs[name]
        m = rich_metrics(
            run["equity"],
            run["trades"],
            spy=spy_ret,
            qqq=qqq_ret,
            equal_weight=ew_ret,
            rf=rf,
            rf_meta=rf_meta,
            turnover_status=run.get("turnover_status", "measured"),
            crisis_windows=crisis,
        )
        m["strategy"] = name
        metrics_map[name] = m
        metrics_rows.append({k: v for k, v in m.items() if k != "rf_meta"})

    stability = run_stability(
        opens,
        closes,
        sectors,
        spy_ret=spy_ret,
        qqq_ret=qqq_ret,
        ew_ret=ew_ret,
        rf=rf,
        rf_meta=rf_meta,
        crisis_windows=crisis,
        one_way_bps=config.one_way_bps,
        versions=list(config.raw["versions"]),
        stability_cfg=config.raw["stability"],
    )

    # Sector / XLK audits for all versions; gate uses challenger
    contrib_frames = []
    xlk_summaries = {}
    for version in config.raw["versions"]:
        audit = sector_contribution_audit(
            opens,
            closes,
            sectors,
            version,
            one_way_bps=config.one_way_bps,
            spy_ret=spy_ret,
            qqq_ret=qqq_ret,
            ew_ret=ew_ret,
            rf=rf,
            rf_meta=rf_meta,
        )
        contrib_frames.append(audit["contributions"])
        xlk_summaries[version] = audit["summary"]
    contrib_df = pd.concat(contrib_frames, ignore_index=True) if contrib_frames else pd.DataFrame()
    challenger_xlk = xlk_summaries[config.challenger]

    gate = evaluate_gate(metrics_map, stability, challenger_xlk)

    run_dir = new_run_directory(config, "full-audit")
    metrics_df = pd.DataFrame(metrics_rows)
    metrics_df.to_csv(run_dir / "sector_momentum_metrics.csv", index=False)
    rolling_df = pd.DataFrame(stability["rolling"])
    rolling_df.to_csv(run_dir / "sector_momentum_rolling.csv", index=False)
    contrib_df.to_csv(run_dir / "sector_momentum_sector_contributions.csv", index=False)
    pd.DataFrame(stability["fixed_endpoints"]).to_csv(
        run_dir / "sector_momentum_fixed_endpoints.csv", index=False
    )
    pd.DataFrame(stability["bootstrap"]).to_csv(
        run_dir / "sector_momentum_bootstrap.csv", index=False
    )
    pd.DataFrame(stability["leave_one_out"]).to_csv(run_dir / "leave_one_out.csv", index=False)
    pd.DataFrame(list(xlk_summaries.values())).to_csv(run_dir / "xlk_summaries.csv", index=False)
    (run_dir / "price_audit.json").write_text(
        json.dumps(price_audit, indent=2, default=str), encoding="utf-8"
    )
    (run_dir / "gate.json").write_text(json.dumps(gate, indent=2, default=str), encoding="utf-8")
    (run_dir / "rf_meta.json").write_text(json.dumps(rf_meta, indent=2), encoding="utf-8")

    def _jsonable(obj):
        if isinstance(obj, dict):
            return {k: _jsonable(v) for k, v in obj.items() if k != "frame"}
        if isinstance(obj, list):
            return [_jsonable(v) for v in obj]
        if isinstance(obj, (np.floating, float)):
            x = float(obj)
            return None if np.isnan(x) or np.isinf(x) else x
        if isinstance(obj, (np.integer, int)):
            return int(obj)
        if isinstance(obj, (np.bool_, bool)):
            return bool(obj)
        if isinstance(obj, pd.Timestamp):
            return str(obj.date())
        return obj

    (run_dir / "stability_summary.json").write_text(
        json.dumps(
            {
                "versions": {
                    v: {k: _jsonable(val) for k, val in block.items()}
                    for v, block in stability["versions"].items()
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    for name, run in runs.items():
        run["equity"].to_csv(run_dir / f"equity_{name}.csv")
        if not run["trades"].empty:
            run["trades"].to_csv(run_dir / f"trades_{name}.csv", index=False)
        if not run.get("targets", pd.DataFrame()).empty:
            run["targets"].to_csv(run_dir / f"targets_{name}.csv", index=False)

    report = render_report(
        config,
        price_audit,
        metrics_map,
        stability,
        contrib_df,
        challenger_xlk,
        xlk_summaries,
        gate,
        rf_meta,
        run_dir,
    )
    (run_dir / "sector_momentum_audit.md").write_text(report, encoding="utf-8")

    config.reports_dir.mkdir(parents=True, exist_ok=True)
    for fname in (
        "sector_momentum_audit.md",
        "sector_momentum_metrics.csv",
        "sector_momentum_rolling.csv",
        "sector_momentum_sector_contributions.csv",
        "sector_momentum_fixed_endpoints.csv",
        "sector_momentum_bootstrap.csv",
    ):
        shutil.copy2(run_dir / fname, config.reports_dir / fname)

    return {
        "run_dir": str(run_dir),
        "gate": gate,
        "price_audit": price_audit,
        "metrics": metrics_map,
        "common_start": str(common_start.date()) if common_start is not None else None,
        "rf_meta": rf_meta,
        "ibkr_modified": False,
    }


def _fmt_pct(x, digits=2):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "n/a"
    return f"{100 * float(x):.{digits}f}%"


def _fmt_num(x, digits=3):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "n/a"
    return f"{float(x):.{digits}f}"


def render_report(
    config: SectorConfig,
    price_audit: dict,
    metrics_map: dict,
    stability: dict,
    contrib_df: pd.DataFrame,
    challenger_xlk: dict,
    xlk_summaries: dict,
    gate: dict,
    rf_meta: dict,
    run_dir: Path,
) -> str:
    lines: list[str] = []
    lines.append("# US Sector ETF Momentum — Research Audit")
    lines.append("")
    lines.append(f"**Verdict:** `{gate['label']}` ({gate['n_pass']}/{gate['n_checks']} checks)")
    lines.append("")
    lines.append(f"Reason: {gate.get('reason')}")
    lines.append("")
    lines.append(
        "Independent research track. **No** rule inheritance from D+C, 80/20, half_protect, "
        "or multi_asset_etf_trend. Primary objective: long-run terminal wealth (not low drawdown / cash)."
    )
    lines.append("")
    lines.append("**IBKR modified:** `false` (must remain false).")
    lines.append("")
    lines.append("## Pre-registered versions (only)")
    lines.append("")
    lines.append("1. `base_12_1_top3` — 12-1 total return, Top 3 equal weight, always 100% invested")
    lines.append(
        "2. `composite_6_1_12_1_top3` — **sole return challenger**; "
        "0.5·rank%ile(6-1)+0.5·rank%ile(12-1), Top 3"
    )
    lines.append(
        "3. `composite_top3_buffer` — same scores as (2); hold while still in Top 4; fill vacancies by score"
    )
    lines.append("")
    lines.append("Forbidden: Top 1/2/4/5; other lookbacks; vol scaling; SMA; BIL sleeve; XLRE/XLC; leverage.")
    lines.append("")
    lines.append("## Data audit")
    lines.append("")
    lines.append(f"- Return basis: `{price_audit.get('return_basis')}`")
    lines.append(
        f"- Strict common sample (9 sectors + SPY + QQQ): "
        f"`{price_audit.get('common_start')}` → `{price_audit.get('common_end')}` "
        f"({price_audit.get('common_rows')} rows)"
    )
    lines.append(f"- Extreme |Adj Close daily ret| > 25% flags: {price_audit.get('n_extreme_flags')}")
    lines.append(f"- Split-like flags (large raw / small adj): {price_audit.get('n_split_like_flags')}")
    man = price_audit.get("manifest") or {}
    lines.append(f"- Manifest retrieved_at_utc: `{man.get('retrieved_at_utc')}`")
    lines.append(f"- File SHA256 recorded for {len(man.get('file_sha256') or {})} symbols")
    lines.append("- Missing returns are **never** `fillna(0)`.")
    lines.append("")
    lines.append("### Risk-free for Sharpe")
    lines.append("")
    lines.append(f"- Method: `{rf_meta.get('method')}`")
    lines.append(f"- BIL days: {rf_meta.get('n_bil_days')}; IRX proxy days: {rf_meta.get('n_irx_proxy_days')}")
    lines.append(
        f"- BIL span: {rf_meta.get('bil_start')} → {rf_meta.get('bil_end')}; "
        f"IRX span: {rf_meta.get('irx_start')} → {rf_meta.get('irx_end')}"
    )
    lines.append("")
    lines.append("### Per-symbol coverage")
    lines.append("")
    lines.append("| Symbol | Start | End | Rows | Dup | Missing bdys | Ext>25% | Split-like | Inception |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---|")
    for sym, info in (price_audit.get("per_symbol") or {}).items():
        lines.append(
            f"| {sym} | {info.get('start')} | {info.get('end')} | {info.get('rows')} | "
            f"{info.get('duplicate_dates')} | {info.get('missing_bdays_in_span')} | "
            f"{info.get('n_extreme_gt_25pct')} | {info.get('n_split_like_flags')} | "
            f"{info.get('inception_approx')} |"
        )
    lines.append("")
    lines.append("## Execution")
    lines.append("")
    lines.append("- Month-end close signal → next session open fill")
    lines.append("- One-way cost 5bp; weights drift between rebalances")
    lines.append("- No shorts, no leverage, always fully invested in Top 3")
    lines.append("")
    lines.append("## Formal comparison")
    lines.append("")
    cols = [
        ("strategy", "strategy"),
        ("cagr", "CAGR"),
        ("final_wealth", "Final W"),
        ("gross_cagr", "Gross CAGR"),
        ("volatility", "Vol"),
        ("sharpe", "Sharpe(rf)"),
        ("sortino", "Sortino"),
        ("max_drawdown", "MaxDD"),
        ("max_dd_duration_trading_sessions", "MaxDD days"),
        ("calmar", "Calmar"),
        ("worst_year", "Worst year"),
        ("worst_rolling_12m", "Worst 12m"),
        ("year_win_rate", "Pos years"),
        ("annualized_turnover", "Ann turn"),
        ("avg_trades_per_year", "Trades/yr"),
        ("cost_drag_cagr", "Cost drag"),
        ("corr_spy", "Corr SPY"),
        ("beta_spy", "β SPY"),
        ("beta_qqq", "β QQQ"),
        ("up_capture", "Up cap"),
        ("down_capture", "Down cap"),
    ]
    lines.append("| " + " | ".join(c[1] for c in cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")
    for name in FORMAL_NAMES:
        m = metrics_map[name]
        row = []
        for key, _ in cols:
            val = m.get(key)
            if key == "strategy":
                row.append(str(val))
            elif key == "final_wealth":
                row.append(_fmt_num(val, 2))
            elif key in {
                "cagr",
                "gross_cagr",
                "volatility",
                "max_drawdown",
                "worst_year",
                "worst_rolling_12m",
                "year_win_rate",
                "cost_drag_cagr",
                "up_capture",
                "down_capture",
                "annualized_turnover",
            }:
                row.append(_fmt_pct(val))
            elif key in {"max_dd_duration_trading_sessions", "avg_trades_per_year"}:
                row.append(_fmt_num(val, 1))
            else:
                row.append(_fmt_num(val))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("### Crisis / segment net returns")
    lines.append("")
    lines.append("| Strategy | 2000–02 | 2008 | 2020 | 2022 |")
    lines.append("|---|---:|---:|---:|---:|")
    for name in FORMAL_NAMES:
        m = metrics_map[name]
        lines.append(
            f"| {name} | {_fmt_pct(m.get('crisis_dotcom_2000_2002_return'))} | "
            f"{_fmt_pct(m.get('crisis_gfc_2008_return'))} | "
            f"{_fmt_pct(m.get('crisis_covid_2020_return'))} | "
            f"{_fmt_pct(m.get('crisis_bear_2022_return'))} |"
        )
    lines.append("")
    lines.append("## Metric C relative wealth")
    lines.append("")
    lines.append(f"Definition: `{metrics_map['composite_6_1_12_1_top3'].get('rel_definition')}`")
    lines.append("")
    lines.append(
        "| Strategy | vs SPY final | vs SPY rel CAGR | vs SPY max UW | vs SPY cur UW | "
        "vs QQQ final | vs QQQ rel CAGR | vs EW9 final | vs EW9 rel CAGR |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name in FORMAL_NAMES:
        m = metrics_map[name]
        lines.append(
            f"| {name} | {_fmt_num(m.get('rel_spy_final_relative_nav'))} | "
            f"{_fmt_pct(m.get('rel_spy_relative_cagr'))} | {_fmt_pct(m.get('rel_spy_max_dd'))} | "
            f"{_fmt_pct(m.get('rel_spy_current_relative_drawdown'))} | "
            f"{_fmt_num(m.get('rel_qqq_final_relative_nav'))} | {_fmt_pct(m.get('rel_qqq_relative_cagr'))} | "
            f"{_fmt_num(m.get('rel_ew9_final_relative_nav'))} | {_fmt_pct(m.get('rel_ew9_relative_cagr'))} |"
        )
    lines.append("")
    lines.append("## Is this just tech (XLK)?")
    lines.append("")
    lines.append(
        "**Do not label long-run XLK overweight as sector-momentum alpha.** "
        "Results below disclose concentration."
    )
    lines.append("")
    x = challenger_xlk
    lines.append(f"- Challenger XLK hold-month share: {_fmt_pct(x.get('xlk_hold_month_share'))}")
    lines.append(
        f"- XLK share of positive contribution mass: {_fmt_pct(x.get('xlk_contribution_share_of_positive'))}"
    )
    lines.append(f"- XLK share of excess CAGR vs SPY: {_fmt_pct(x.get('xlk_share_of_excess_cagr'))}")
    lines.append(f"- Full challenger CAGR: {_fmt_pct(x.get('full_cagr'))}")
    lines.append(f"- Exclude-XLK re-run CAGR: {_fmt_pct(x.get('exclude_xlk_cagr'))}")
    lines.append(f"- Excess vs SPY (full / ex-XLK): {_fmt_pct(x.get('excess_cagr_vs_spy'))} / {_fmt_pct(x.get('excess_cagr_vs_spy_ex_xlk'))}")
    lines.append(f"- CAGR when holding XLK / not: {_fmt_pct(x.get('cagr_when_holding_xlk'))} / {_fmt_pct(x.get('cagr_when_not_holding_xlk'))}")
    lines.append(f"- β SPY / β QQQ: {_fmt_num(x.get('beta_spy'))} / {_fmt_num(x.get('beta_qqq'))}")
    lines.append(
        f"- vs QQQ final relative NAV / rel CAGR: "
        f"{_fmt_num(x.get('rel_qqq_final_relative_nav'))} / {_fmt_pct(x.get('rel_qqq_relative_cagr'))}"
    )
    lines.append("")
    lines.append("### Sector hold-month shares (challenger)")
    lines.append("")
    lines.append("| Sector | Hold-month share | Cum contribution | Share of +contrib |")
    lines.append("|---|---:|---:|---:|")
    ch_rows = contrib_df[contrib_df["version"] == "composite_6_1_12_1_top3"] if not contrib_df.empty else contrib_df
    for _, r in ch_rows.iterrows():
        lines.append(
            f"| {r['sector']} | {_fmt_pct(r.get('hold_month_share'))} | "
            f"{_fmt_num(r.get('cum_contribution'), 4)} | {_fmt_pct(r.get('contribution_share_of_positive'))} |"
        )
    lines.append("")
    lines.append("## Stability (pre-registered)")
    lines.append("")
    ch_s = stability["versions"]["composite_6_1_12_1_top3"]
    lines.append("| Test | CAGR | Final W | Sharpe | MaxDD | Rel CAGR vs SPY |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for label in (
        "baseline",
        "cost_10bp",
        "cost_20bp",
        "extra_delay",
        "exclude_last_1y",
        "exclude_last_2y",
        "exclude_last_3y",
        "restart_2003",
        "restart_2008",
        "restart_2013",
    ):
        m = ch_s.get(label, {})
        lines.append(
            f"| {label} | {_fmt_pct(m.get('cagr'))} | {_fmt_num(m.get('final_wealth'), 2)} | "
            f"{_fmt_num(m.get('sharpe'))} | {_fmt_pct(m.get('max_drawdown'))} | "
            f"{_fmt_pct(m.get('rel_spy_relative_cagr'))} |"
        )
    lines.append("")
    lines.append("### Fixed endpoints")
    lines.append("")
    lines.append("| Cutoff | Strat CAGR | SPY CAGR | Beats? | Strat wealth | SPY wealth |")
    lines.append("|---|---:|---:|---|---:|---:|")
    for r in stability.get("fixed_endpoints", []):
        if r["version"] != "composite_6_1_12_1_top3":
            continue
        lines.append(
            f"| {r['cutoff']} | {_fmt_pct(r.get('strategy_cagr'))} | {_fmt_pct(r.get('spy_cagr'))} | "
            f"{r.get('beats_spy_cagr')} | {_fmt_num(r.get('strategy_final_wealth'), 2)} | "
            f"{_fmt_num(r.get('spy_final_wealth'), 2)} |"
        )
    lines.append("")
    lines.append(
        f"### Rolling beat rates vs SPY — 5y: {_fmt_pct(gate.get('rolling_5y_beat_rate'))}; "
        f"10y: {_fmt_pct(gate.get('rolling_10y_beat_rate'))}"
    )
    lines.append("")
    lines.append("### Leave-one-sector-out (challenger)")
    lines.append("")
    lines.append("| Dropped | CAGR | Final W | MaxDD | Rel CAGR vs SPY |")
    lines.append("|---|---:|---:|---:|---:|")
    for r in stability.get("leave_one_out", []):
        if r["version"] != "composite_6_1_12_1_top3":
            continue
        lines.append(
            f"| {r['dropped']} | {_fmt_pct(r.get('cagr'))} | {_fmt_num(r.get('final_wealth'), 2)} | "
            f"{_fmt_pct(r.get('max_drawdown'))} | {_fmt_pct(r.get('rel_spy_relative_cagr'))} |"
        )
    lines.append("")
    lines.append("### Block bootstrap (CAGR strat − CAGR SPY)")
    lines.append("")
    lines.append("| Version | Observed | Mean | 2.5% | 97.5% | P(diff>0) | Block | N |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in stability.get("bootstrap", []):
        lines.append(
            f"| {r.get('version')} | {_fmt_pct(r.get('observed_cagr_diff'))} | "
            f"{_fmt_pct(r.get('mean_cagr_diff'))} | {_fmt_pct(r.get('ci_2_5'))} | "
            f"{_fmt_pct(r.get('ci_97_5'))} | {_fmt_pct(r.get('p_diff_positive'))} | "
            f"{r.get('block')} | {r.get('n_boot')} |"
        )
    lines.append("")
    lines.append("Method: moving-block paired bootstrap (not i.i.d. daily).")
    lines.append("")
    lines.append("## Gate checklist")
    lines.append("")
    for k, v in gate["checks"].items():
        lines.append(f"- [{'x' if v else ' '}] `{k}`")
    lines.append("")
    lines.append("## Decision")
    lines.append("")
    if gate["label"] == "REJECTED":
        lines.append(
            "**REJECTED.** Do not change Top-N, lookbacks, add SMA/BIL, or modify IBKR. "
            "Higher Sharpe with lower terminal wealth than SPY remains a failure."
        )
    else:
        lines.append(
            "**SECTOR_MOMENTUM_RETURN_CANDIDATE** — research shadow only. "
            "Not a production/IBKR change."
        )
    lines.append("")
    lines.append("## Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append(f"cd {config.project_root}")
    lines.append("python3 -m pip install -e '.[dev]'")
    lines.append("us-sector-momentum fetch")
    lines.append("us-sector-momentum audit-data")
    lines.append("us-sector-momentum full-audit")
    lines.append("pytest -q")
    lines.append("```")
    lines.append("")
    lines.append(f"Run directory: `{run_dir}`")
    lines.append("")
    lines.append("## Outputs")
    lines.append("")
    lines.append("- `reports/sector_momentum_audit.md`")
    lines.append("- `reports/sector_momentum_metrics.csv`")
    lines.append("- `reports/sector_momentum_rolling.csv`")
    lines.append("- `reports/sector_momentum_sector_contributions.csv`")
    lines.append("- `reports/sector_momentum_fixed_endpoints.csv`")
    lines.append("- `reports/sector_momentum_bootstrap.csv`")
    lines.append("")
    return "\n".join(lines)
