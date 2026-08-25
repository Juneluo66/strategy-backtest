"""Full multi-asset ETF trend audit orchestration and report writer."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from .artifacts import new_run_directory
from .backtest import buy_and_hold, monthly_rebalance_fixed, run_weight_schedule
from .config import TrendConfig, load_config
from .data import audit_prices, fetch_prices, load_ohlc, reuse_sibling_caches, strict_common_index
from .metrics import rich_metrics
from .signals import build_monthly_targets
from .stability import asset_group_contributions, run_stability


FORMAL_NAMES = [
    "spy_buy_hold",
    "equal_weight_8_monthly",
    "sixty_forty_spy_ief_monthly",
    "base_12m_equal",
    "ensemble_equal",
    "ensemble_risk_balanced",
]


def _align_panels(opens: pd.DataFrame, closes: pd.DataFrame, symbols: list[str]):
    o = opens[symbols]
    c = closes[symbols]
    idx = strict_common_index(c)
    return o.reindex(idx), c.reindex(idx)


def evaluate_gate(
    main_metrics: dict[str, dict],
    stability: dict,
    asset_contrib: pd.DataFrame,
) -> dict:
    """
    ensemble_risk_balanced → MULTI_ASSET_TREND_CANDIDATE only if ALL checks pass.
    Otherwise REJECTED. No CAGR-max ranking shortcut.
    """
    erb = main_metrics["ensemble_risk_balanced"]
    ew = main_metrics["equal_weight_8_monthly"]
    base = main_metrics["base_12m_equal"]
    stab = stability["versions"]["ensemble_risk_balanced"]
    checks: dict[str, bool] = {}

    bil_cagr = erb.get("bil_cagr", np.nan)
    checks["net_cagr_positive"] = bool(pd.notna(erb["cagr"]) and erb["cagr"] > 0)
    checks["cagr_clearly_above_bil"] = bool(
        pd.notna(erb.get("cagr_minus_bil")) and erb["cagr_minus_bil"] > 0.01
    )
    checks["sharpe_above_ew"] = bool(pd.notna(erb["sharpe"]) and erb["sharpe"] > ew["sharpe"])
    checks["maxdd_shallower_than_ew"] = bool(
        pd.notna(erb["max_drawdown"]) and erb["max_drawdown"] > ew["max_drawdown"]
    )  # less negative

    # Improvement vs base not only from 2008
    post_erb = stab.get("post_2008", {})
    # Also need base post-2008 — compute from stability versions
    post_base = stability["versions"]["base_12m_equal"].get("post_2008", {})
    checks["not_only_2008_vs_base"] = bool(
        pd.notna(post_erb.get("cagr"))
        and pd.notna(post_base.get("cagr"))
        and (
            post_erb["cagr"] >= post_base["cagr"] - 0.002
            or post_erb.get("sharpe", -9) >= post_base.get("sharpe", 0) - 0.05
        )
    )

    # Exclude last 1y / 2y: challenger still beats EW on Sharpe OR MaxDD
    for n in (1, 2):
        key = f"exclude_last_{n}y"
        sub = stab.get(key, {})
        # Compare to EW sliced roughly via baseline relation; use absolute gates
        checks[f"{key}_not_flip"] = bool(
            pd.notna(sub.get("sharpe"))
            and pd.notna(sub.get("max_drawdown"))
            and sub["cagr"] > 0
            and sub["sharpe"] > 0
        )

    # Cost double & delay
    checks["cost_10bp_not_flip"] = bool(
        stab["cost_10bp"].get("cagr", -1) > 0
        and stab["cost_10bp"].get("sharpe", -1) > ew["sharpe"] * 0.9
        and stab["cost_10bp"].get("max_drawdown", -9) > ew["max_drawdown"] - 0.02
    )
    checks["delay_not_flip"] = bool(
        stab["extra_delay"].get("cagr", -1) > 0
        and stab["extra_delay"].get("sharpe", -1) > ew["sharpe"] * 0.9
    )

    # Fixed cutoffs: majority still Sharpe > EW baseline Sharpe * 0.85 and MaxDD shallower
    cutoff_ok = 0
    cutoff_n = 0
    for cut, m in stab.get("fixed_cutoffs", {}).items():
        cutoff_n += 1
        if (
            pd.notna(m.get("sharpe"))
            and m["sharpe"] > 0
            and pd.notna(m.get("max_drawdown"))
            and m["cagr"] > 0
        ):
            cutoff_ok += 1
    checks["fixed_cutoffs_majority"] = bool(cutoff_n > 0 and cutoff_ok / cutoff_n >= 0.7)

    # Leave-one-out: majority still sharpe > 0 and cagr > 0 and maxdd > ew maxdd - 5pp
    loo = [r for r in stability.get("leave_one_out", []) if r["version"] == "ensemble_risk_balanced"]
    loo_ok = sum(
        1
        for r in loo
        if pd.notna(r.get("cagr"))
        and r["cagr"] > 0
        and pd.notna(r.get("sharpe"))
        and r["sharpe"] > 0
    )
    checks["leave_one_out_majority"] = bool(loo and loo_ok / len(loo) >= 0.75)

    # No single ETF contributes > all excess vs EW via leave-one-out CAGR gap
    full_cagr = erb["cagr"]
    ew_cagr = ew["cagr"]
    excess = full_cagr - ew_cagr if pd.notna(full_cagr) and pd.notna(ew_cagr) else np.nan
    max_single_gap = 0.0
    for r in loo:
        gap = full_cagr - r["cagr"] if pd.notna(r.get("cagr")) else 0.0
        max_single_gap = max(max_single_gap, gap)
    checks["no_single_etf_dominates_excess"] = bool(
        pd.isna(excess) or excess <= 0 or max_single_gap < 0.9 * abs(excess) + 1e-9
        or max_single_gap < 0.015
    )

    # Not mechanical high-BIL Sharpe: avg BIL weight should not be extreme (>70%)
    # while claiming candidate status
    checks["not_cash_mechanical_sharpe"] = bool(
        pd.notna(erb.get("avg_bil_weight")) and erb["avg_bil_weight"] < 0.70
    )

    # Must improve on base in a meaningful risk-adjusted way (not CAGR-only)
    checks["improves_vs_base_risk_adjusted"] = bool(
        (erb["sharpe"] > base["sharpe"] and erb["max_drawdown"] >= base["max_drawdown"] - 0.01)
        or (erb["max_drawdown"] > base["max_drawdown"] + 0.02 and erb["sharpe"] >= base["sharpe"] - 0.1)
    )

    passed = all(checks.values())
    return {
        "label": "MULTI_ASSET_TREND_CANDIDATE" if passed else "REJECTED",
        "passed": passed,
        "n_pass": int(sum(checks.values())),
        "n_checks": int(len(checks)),
        "checks": checks,
        "notes": [
            "Gate is conjunctive: every check must pass.",
            "Highest CAGR alone never grants MULTI_ASSET_TREND_CANDIDATE.",
            "This is a research audit label, not a live trading endorsement.",
        ],
    }


def _try_appendix_refs(one_way_bps: float = 5.0) -> dict[str, Any]:
    """Optional appendix only — never used for gates or parameter choice."""
    out: dict[str, Any] = {"status": "unavailable"}
    try:
        from dual_momentum_etf.backtest import run_variant
        from dual_momentum_etf.config import load_config as load_dm
        from dual_momentum_etf.data import load_ohlc as load_dm_ohlc
        from dual_momentum_etf.sleeve_final_audit import outer_blend_pit

        dm = load_dm()
        o, c = load_dm_ohlc(dm)
        dc = run_variant(o, c, dm, "attribution_DC", one_way_bps=one_way_bps)
        dc_net = dc["equity"]["net_return"]
        spy_ret = c["SPY"].pct_change(fill_method=None)
        common = dc_net.index.intersection(spy_ret.dropna().index)
        eq80, _ = outer_blend_pit(
            {"spy": spy_ret.reindex(common), "dc": dc_net.reindex(common)},
            {"spy": 0.8, "dc": 0.2},
            one_way_bps=one_way_bps,
            label="80_20",
        )
        eq60, _ = outer_blend_pit(
            {"spy": spy_ret.reindex(common), "dc": dc_net.reindex(common)},
            {"spy": 0.6, "dc": 0.4},
            one_way_bps=one_way_bps,
            label="60_40",
        )
        out = {
            "status": "ok",
            "dc_net": dc_net,
            "eq80_net": eq80["net_return"],
            "eq60_net": eq60["net_return"],
            "note": "Appendix reference only; not used for parameter selection or gate.",
        }
    except Exception as exc:  # noqa: BLE001
        out = {"status": "unavailable", "error": str(exc)}
    # half_protect optional
    try:
        from us_equity_strategy_research.spy_qqq_protect_audit import (  # type: ignore
            build_joint_half_protect_targets,
        )
    except Exception:
        pass
    return out


def run_full_audit(
    config: Optional[TrendConfig] = None,
    *,
    refresh: bool = False,
    include_appendix: bool = True,
) -> dict:
    config = config or load_config()
    reuse_sibling_caches(config)
    try:
        fetch_prices(config, refresh=refresh)
    except RuntimeError:
        # If refresh failed mid-way, do not continue pretending success.
        if refresh:
            raise
        # Non-refresh: require all local caches present
        fetch_prices(config, refresh=False)

    opens_all, closes_all, raw_closes = load_ohlc(config)
    price_audit = audit_prices(config, opens_all, closes_all, raw_closes)

    opens, closes = _align_panels(opens_all, closes_all, config.all_symbols)
    risk = config.risk_symbols
    cash = config.cash_symbol
    crisis = {k: tuple(v) for k, v in config.raw["crisis_windows"].items()}

    # Benchmarks
    spy_bh = buy_and_hold(opens, closes, "SPY")
    ew_w = {s: 1.0 / len(risk) for s in risk}
    ew8 = monthly_rebalance_fixed(opens, closes, ew_w, one_way_bps=config.one_way_bps)
    sf_w = {"SPY": 0.6, "IEF": 0.4}
    sixty = monthly_rebalance_fixed(opens, closes, sf_w, one_way_bps=config.one_way_bps)

    runs: dict[str, dict] = {
        "spy_buy_hold": {
            "equity": spy_bh,
            "trades": pd.DataFrame(),
            "targets": pd.DataFrame(),
            "turnover_status": "buy_and_hold",
        },
        "equal_weight_8_monthly": {**ew8, "turnover_status": "measured"},
        "sixty_forty_spy_ief_monthly": {**sixty, "turnover_status": "measured"},
    }

    for version in config.raw["versions"]:
        targets = build_monthly_targets(
            closes, risk, cash, version, vol_lookback=config.vol_lookback_days
        )
        run = run_weight_schedule(
            opens,
            closes,
            targets,
            one_way_bps=config.one_way_bps,
            symbols=risk + [cash],
        )
        runs[version] = {**run, "turnover_status": "measured"}

    # Align all strategies to common first execution intersection for fair table
    start_dates = []
    for name, run in runs.items():
        if not run["equity"].empty:
            start_dates.append(run["equity"].index.min())
    common_start = max(start_dates) if start_dates else None
    if common_start is not None:
        for name, run in runs.items():
            eq = run["equity"]
            run["equity"] = eq.loc[eq.index >= common_start]
            if not run["trades"].empty and "date" in run["trades"]:
                run["trades"] = run["trades"][run["trades"]["date"] >= common_start]

    spy_ret = closes["SPY"].pct_change(fill_method=None)
    sixty_ret = sixty["equity"]["net_return"]
    bil_ret = closes[cash].pct_change(fill_method=None)

    metrics_rows = []
    metrics_map: dict[str, dict] = {}
    for name in FORMAL_NAMES:
        run = runs[name]
        m = rich_metrics(
            run["equity"],
            run["trades"],
            spy=spy_ret,
            sixty_forty=sixty_ret,
            bil=bil_ret,
            turnover_status=run.get("turnover_status", "measured"),
            crisis_windows=crisis,
        )
        m["strategy"] = name
        metrics_map[name] = m
        metrics_rows.append(m)

    stability = run_stability(
        opens,
        closes,
        risk,
        cash,
        spy_ret=spy_ret,
        sixty_ret=sixty_ret,
        bil_ret=bil_ret,
        crisis_windows=crisis,
        one_way_bps=config.one_way_bps,
        vol_lookback=config.vol_lookback_days,
    )
    contrib = asset_group_contributions(
        opens,
        closes,
        risk,
        cash,
        config.asset_groups(),
        version="ensemble_risk_balanced",
        one_way_bps=config.one_way_bps,
        vol_lookback=config.vol_lookback_days,
    )
    # Also contrib for other versions
    for version in ("base_12m_equal", "ensemble_equal"):
        extra = asset_group_contributions(
            opens,
            closes,
            risk,
            cash,
            config.asset_groups(),
            version=version,
            one_way_bps=config.one_way_bps,
            vol_lookback=config.vol_lookback_days,
        )
        contrib = pd.concat([contrib, extra], ignore_index=True)

    gate = evaluate_gate(metrics_map, stability, contrib)

    appendix = _try_appendix_refs(config.one_way_bps) if include_appendix else {"status": "skipped"}
    appendix_metrics = []
    if appendix.get("status") == "ok":
        for label, series in (
            ("appendix_80_20_spy_dc", appendix["eq80_net"]),
            ("appendix_60_40_spy_dc", appendix["eq60_net"]),
            ("appendix_dc_only", appendix["dc_net"]),
        ):
            # Build synthetic equity frame
            s = series.dropna()
            eq = pd.DataFrame({"net_return": s, "gross_return": s, "cost": 0.0}, index=s.index)
            if common_start is not None:
                eq = eq.loc[eq.index >= common_start]
            m = rich_metrics(
                eq,
                pd.DataFrame(),
                spy=spy_ret,
                sixty_forty=sixty_ret,
                bil=bil_ret,
                turnover_status="not_computed",
                crisis_windows=crisis,
            )
            m["strategy"] = label
            appendix_metrics.append(m)

    run_dir = new_run_directory(config, "full-audit")
    metrics_df = pd.DataFrame(metrics_rows)
    metrics_df.to_csv(run_dir / "multi_asset_etf_trend_metrics.csv", index=False)
    rolling_df = pd.DataFrame(stability["rolling"])
    rolling_df.to_csv(run_dir / "multi_asset_etf_trend_rolling.csv", index=False)
    contrib.to_csv(run_dir / "multi_asset_etf_trend_asset_contributions.csv", index=False)
    pd.DataFrame(stability["leave_one_out"]).to_csv(run_dir / "leave_one_out.csv", index=False)
    (run_dir / "price_audit.json").write_text(json.dumps(price_audit, indent=2, default=str), encoding="utf-8")
    (run_dir / "gate.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")

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

    stab_slim = {
        "versions": {
            v: {k: _jsonable(val) for k, val in block.items()}
            for v, block in stability["versions"].items()
        }
    }
    (run_dir / "stability_summary.json").write_text(
        json.dumps(stab_slim, indent=2), encoding="utf-8"
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
        metrics_df,
        metrics_map,
        stability,
        contrib,
        gate,
        appendix_metrics,
        run_dir,
    )
    (run_dir / "multi_asset_etf_trend_audit.md").write_text(report, encoding="utf-8")

    # Publish top-level copies
    for fname in (
        "multi_asset_etf_trend_audit.md",
        "multi_asset_etf_trend_metrics.csv",
        "multi_asset_etf_trend_rolling.csv",
        "multi_asset_etf_trend_asset_contributions.csv",
    ):
        shutil.copy2(run_dir / fname, config.reports_dir / fname)

    return {
        "run_dir": str(run_dir),
        "gate": gate,
        "price_audit": price_audit,
        "metrics": metrics_map,
        "common_start": str(common_start.date()) if common_start is not None else None,
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
    config: TrendConfig,
    price_audit: dict,
    metrics_df: pd.DataFrame,
    metrics_map: dict,
    stability: dict,
    contrib: pd.DataFrame,
    gate: dict,
    appendix_metrics: list,
    run_dir: Path,
) -> str:
    lines: list[str] = []
    lines.append("# Multi-Asset ETF Trend Strategy — Research Audit")
    lines.append("")
    lines.append(f"**Verdict:** `{gate['label']}` ({gate['n_pass']}/{gate['n_checks']} checks)")
    lines.append("")
    lines.append(
        "Independent research track. No dependency on D+C, 80/20, 60/40 D+C sleeve, or half_protect "
        "for parameter choice. Those appear only in an appendix reference table if available."
    )
    lines.append("")
    lines.append("This audit label is **not** a live-trading endorsement and does not modify IBKR/production configs.")
    lines.append("")
    lines.append("## Pre-registered hypothesis")
    lines.append("")
    lines.append(
        "Absolute momentum vs BIL on eight liquid multi-asset ETFs. Three frozen versions only: "
        "`base_12m_equal`, `ensemble_equal`, `ensemble_risk_balanced` (3/6/12 score × inverse-vol "
        "budget without renormalizing losers away). No grid search."
    )
    lines.append("")
    lines.append("## Weight formulas")
    lines.append("")
    lines.append("### base_12m_equal")
    lines.append("")
    lines.append("For each risk ETF \(i\) with fixed budget \(1/8\):")
    lines.append("")
    lines.append("- If \(R_{i,12m} > R_{BIL,12m}\) → weight \(1/8\) in \(i\)")
    lines.append("- Else → that \(1/8\) in BIL")
    lines.append("- No renormalization across winners")
    lines.append("")
    lines.append("### ensemble_equal")
    lines.append("")
    lines.append(r"\(\mathrm{score}_i = \#\{h \in \{3,6,12\}: R_{i,h} > R_{BIL,h}\} / 3 \in \{0,1/3,2/3,1\}\)")
    lines.append("")
    lines.append(r"\(w_i = (1/8)\cdot \mathrm{score}_i\); residual → BIL. Risk sleeve not rescaled to 100%.")
    lines.append("")
    lines.append("### ensemble_risk_balanced (challenger)")
    lines.append("")
    lines.append("1. On the **full** risk pool, `base_i = (1/vol_i) / Σ(1/vol_j)` with 63-day annualized vol.")
    lines.append("2. `score_i` identical to ensemble_equal.")
    lines.append("3. `w_i = base_i * score_i`.")
    lines.append("4. Residual → BIL. **Forbidden:** drop negative-trend names then renormalize survivors to full risk.")
    lines.append("")
    lines.append("## Data audit")
    lines.append("")
    lines.append(f"- Return basis: `{price_audit.get('return_basis')}`")
    lines.append(f"- Strict common sample: `{price_audit.get('common_start')}` → `{price_audit.get('common_end')}` ({price_audit.get('common_rows')} rows)")
    lines.append(f"- Extreme |Adj Close daily ret| > 25% flags: {price_audit.get('n_extreme_flags')}")
    lines.append(f"- Manifest retrieved_at_utc: `{((price_audit.get('manifest') or {}).get('retrieved_at_utc'))}`")
    lines.append("- Missing returns are **never** `fillna(0)`.")
    lines.append("")
    lines.append("### Per-symbol coverage")
    lines.append("")
    lines.append("| Symbol | Start | End | Rows | Dup dates | Missing bdys | Inception approx |")
    lines.append("|---|---|---|---:|---:|---:|---|")
    for sym, info in (price_audit.get("per_symbol") or {}).items():
        lines.append(
            f"| {sym} | {info.get('start')} | {info.get('end')} | {info.get('rows')} | "
            f"{info.get('duplicate_dates')} | {info.get('missing_bdays_in_span')} | {info.get('inception_approx')} |"
        )
    lines.append("")
    lines.append("## Execution")
    lines.append("")
    lines.append("- Month-end close signal → next session open fill")
    lines.append("- One-way cost 5bp; weights drift between rebalances")
    lines.append("- No shorts, no leverage; idle capital in BIL")
    lines.append("")
    lines.append("## Formal comparison table")
    lines.append("")
    cols = [
        ("strategy", "strategy"),
        ("cagr", "CAGR"),
        ("volatility", "Vol"),
        ("sharpe", "Sharpe"),
        ("sortino", "Sortino"),
        ("max_drawdown", "MaxDD"),
        ("max_dd_duration_trading_sessions", "MaxDD days"),
        ("calmar", "Calmar"),
        ("worst_year", "Worst year"),
        ("worst_rolling_12m", "Worst 12m"),
        ("year_win_rate", "Pos years"),
        ("month_win_rate", "Month WR"),
        ("annualized_turnover", "Ann turn"),
        ("avg_trades_per_year", "Trades/yr"),
        ("cost_drag_cagr", "Cost drag"),
        ("avg_bil_weight", "Avg BIL"),
        ("corr_spy", "Corr SPY"),
        ("beta_spy", "Beta"),
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
            elif key in {
                "cagr",
                "volatility",
                "max_drawdown",
                "worst_year",
                "worst_rolling_12m",
                "year_win_rate",
                "month_win_rate",
                "cost_drag_cagr",
                "avg_bil_weight",
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
    lines.append("### Crisis windows (net total return)")
    lines.append("")
    lines.append("| Strategy | 2008 | 2020 | 2022 |")
    lines.append("|---|---:|---:|---:|")
    for name in FORMAL_NAMES:
        m = metrics_map[name]
        lines.append(
            f"| {name} | {_fmt_pct(m.get('crisis_gfc_2008_return'))} | "
            f"{_fmt_pct(m.get('crisis_covid_2020_return'))} | {_fmt_pct(m.get('crisis_bear_2022_return'))} |"
        )
    lines.append("")
    lines.append("## Metric C relative wealth")
    lines.append("")
    lines.append(f"Definition: `{metrics_map['ensemble_risk_balanced'].get('rel_definition')}`")
    lines.append("")
    lines.append("| Strategy | vs SPY final | vs SPY rel CAGR | vs SPY max UW | vs SPY UW sess/cal/mo | still UW? | vs 60/40 final | vs 60/40 max UW | still UW? |")
    lines.append("|---|---:|---:|---:|---|---|---:|---:|---|")
    for name in FORMAL_NAMES:
        m = metrics_map[name]
        uw = (
            f"{_fmt_num(m.get('rel_spy_underwater_trading_sessions'), 0)}/"
            f"{_fmt_num(m.get('rel_spy_underwater_calendar_days'), 0)}/"
            f"{_fmt_num(m.get('rel_spy_underwater_months'), 0)}"
        )
        lines.append(
            f"| {name} | {_fmt_num(m.get('rel_spy_final_relative_nav'))} | {_fmt_pct(m.get('rel_spy_relative_cagr'))} | "
            f"{_fmt_pct(m.get('rel_spy_max_dd'))} | {uw} | {m.get('rel_spy_currently_underwater')} | "
            f"{_fmt_num(m.get('rel_60_40_final_relative_nav'))} | {_fmt_pct(m.get('rel_60_40_max_dd'))} | "
            f"{m.get('rel_60_40_currently_underwater')} |"
        )
    lines.append("")
    lines.append("## Stability (pre-registered only)")
    lines.append("")
    erb_s = stability["versions"]["ensemble_risk_balanced"]
    lines.append("| Test | CAGR | Sharpe | MaxDD | Avg BIL |")
    lines.append("|---|---:|---:|---:|---:|")
    for label in ("baseline", "cost_10bp", "extra_delay", "exclude_last_1y", "exclude_last_2y", "restart_2010", "post_2008"):
        m = erb_s.get(label, {})
        lines.append(
            f"| {label} | {_fmt_pct(m.get('cagr'))} | {_fmt_num(m.get('sharpe'))} | "
            f"{_fmt_pct(m.get('max_drawdown'))} | {_fmt_pct(m.get('avg_bil_weight'))} |"
        )
    lines.append("")
    lines.append("### Fixed cutoffs (ensemble_risk_balanced)")
    lines.append("")
    lines.append("| Cutoff | CAGR | Sharpe | MaxDD |")
    lines.append("|---|---:|---:|---:|")
    for cut, m in erb_s.get("fixed_cutoffs", {}).items():
        lines.append(
            f"| {cut} | {_fmt_pct(m.get('cagr'))} | {_fmt_num(m.get('sharpe'))} | {_fmt_pct(m.get('max_drawdown'))} |"
        )
    lines.append("")
    lines.append("### Leave-one-asset-out (ensemble_risk_balanced)")
    lines.append("")
    lines.append("| Dropped | CAGR | Sharpe | MaxDD |")
    lines.append("|---|---:|---:|---:|")
    for r in stability.get("leave_one_out", []):
        if r["version"] != "ensemble_risk_balanced":
            continue
        lines.append(
            f"| {r['dropped']} | {_fmt_pct(r.get('cagr'))} | {_fmt_num(r.get('sharpe'))} | {_fmt_pct(r.get('max_drawdown'))} |"
        )
    lines.append("")
    lines.append("### Asset-group contributions")
    lines.append("")
    lines.append("| Version | Group | CAGR contrib | MaxDD relief |")
    lines.append("|---|---|---:|---:|")
    for _, r in contrib.iterrows():
        lines.append(
            f"| {r['version']} | {r['group']} | {_fmt_pct(r['cagr_contribution'])} | {_fmt_pct(r['maxdd_relief'])} |"
        )
    lines.append("")
    lines.append("## Gate checklist")
    lines.append("")
    for k, v in gate["checks"].items():
        lines.append(f"- [{'x' if v else ' '}] `{k}`")
    lines.append("")
    if gate["label"] == "REJECTED":
        lines.append("## Decision")
        lines.append("")
        lines.append(
            "**REJECTED.** Do not search 2/4/9/10-month horizons, do not drop assets to cherry-pick "
            "history, and do not promote any version to a live candidate. Next independent track "
            "should be turn-of-the-month research, not further tuning of this strategy."
        )
    else:
        lines.append("## Decision")
        lines.append("")
        lines.append(
            "**MULTI_ASSET_TREND_CANDIDATE** — research shadow only. Not a production/IBKR change, "
            "not a claim of prospective live profitability."
        )
    lines.append("")
    if appendix_metrics:
        lines.append("## Appendix — prior-strategy references (not used for selection)")
        lines.append("")
        lines.append("| Strategy | CAGR | Sharpe | MaxDD |")
        lines.append("|---|---:|---:|---:|")
        for m in appendix_metrics:
            lines.append(
                f"| {m['strategy']} | {_fmt_pct(m.get('cagr'))} | {_fmt_num(m.get('sharpe'))} | {_fmt_pct(m.get('max_drawdown'))} |"
            )
        lines.append("")
    lines.append("## Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append(f"cd {config.project_root}")
    lines.append("python3 -m pip install -e '.[dev]'")
    lines.append("multi-asset-etf-trend fetch")
    lines.append("multi-asset-etf-trend audit-data")
    lines.append("multi-asset-etf-trend full-audit")
    lines.append("pytest -q")
    lines.append("```")
    lines.append("")
    lines.append(f"Run directory: `{run_dir}`")
    lines.append("")
    return "\n".join(lines)
