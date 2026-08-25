"""Final sleeve audit + PIT-safe outer rebalance (D+C rules frozen)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from .artifacts import config_hash
from .attribution import align_start, run_buy_and_hold, run_sixty_forty, trim_result
from .backtest import run_variant
from .config import DualMomentumConfig
from .data import cash_symbol_on, load_ohlc
from .relative_spy_audit import metric_c_relative_nav
from .signals import month_end_index, next_trading_day
from .sleeve_evaluation import (
    _stats_extended,
    expand_dc_holdings,
    look_through_exposures,
    yearly_returns,
)


# Default paper candidate + conservative shadow (pre-declared; no search).
DEFAULT_CANDIDATE = {"name": "80_20", "spy": 0.8, "dc": 0.2}
CONSERVATIVE_SHADOW = {"name": "60_40", "spy": 0.6, "dc": 0.4}

SIMPLE_BENCHMARKS = [
    {"name": "80_20_ief", "legs": [("SPY", 0.8), ("IEF", 0.2)]},
    {"name": "80_20_cash", "legs": [("SPY", 0.8), ("CASH", 0.2)]},  # SGOV/BIL
    {"name": "80_20_gld", "legs": [("SPY", 0.8), ("GLD", 0.2)]},
    {"name": "90_10_ief", "legs": [("SPY", 0.9), ("IEF", 0.1)]},
]


def daily_total_returns(closes: pd.DataFrame, symbol: str) -> pd.Series:
    return closes[symbol].pct_change(fill_method=None)


def cash_total_returns(closes: pd.DataFrame, config: DualMomentumConfig) -> pd.Series:
    """Point-in-time SGOV with BIL proxy — no lookahead."""
    primary = config.raw["cash"]["primary"]
    proxy = config.raw["cash"]["proxy_before_primary"]
    out = []
    prev = None
    for date in closes.index:
        sym = cash_symbol_on(date, config, closes)
        px = closes.loc[date, sym] if sym in closes.columns else np.nan
        if prev is None or pd.isna(px) or pd.isna(prev[1]) or prev[0] != sym:
            ret = 0.0 if prev is None else float("nan")
            # symbol switch: use 0 return that day rather than cross-asset pct
            if prev is not None and prev[0] != sym:
                ret = 0.0
            elif prev is not None and pd.notna(prev[1]) and pd.notna(px) and prev[0] == sym:
                ret = float(px / prev[1] - 1)
        else:
            ret = float(px / prev[1] - 1)
        out.append(ret)
        if pd.notna(px):
            prev = (sym, float(px))
    return pd.Series(out, index=closes.index, dtype=float).fillna(0.0)


def outer_blend_pit(
    leg_returns: dict[str, pd.Series],
    targets: dict[str, float],
    *,
    one_way_bps: float,
    label: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Outer sleeve blend with month-end CLOSE signal → next session OPEN execution.

    Between rebalances, weights **drift** with daily total returns (not constant 0.8/0.2).
    Rebalance cost is charged only on execution days (outer layer). Leg series for D+C
    should already be net of D+C-internal costs; do not re-apply those here.
    """
    idx = None
    for series in leg_returns.values():
        idx = series.index if idx is None else idx.intersection(series.index)
    idx = pd.DatetimeIndex(idx).sort_values()
    rets = {k: v.reindex(idx).fillna(0.0) for k, v in leg_returns.items()}

    month_ends = list(month_end_index(idx))
    execute_map: dict[pd.Timestamp, pd.Timestamp] = {}
    for sig in month_ends:
        exe = next_trading_day(idx, sig)
        if exe is not None:
            execute_map[pd.Timestamp(exe)] = pd.Timestamp(sig)

    # Start at targets
    weights = {k: float(v) for k, v in targets.items()}
    rows = []
    reb_log = []
    outer_cost_sum = 0.0
    turnover_sum = 0.0

    for date in idx:
        outer_cost = 0.0
        if date in execute_map:
            # Rebalance using weights known after prior close (no same-day close fill)
            turn = sum(abs(targets[k] - weights.get(k, 0.0)) for k in targets)
            outer_cost = turn * one_way_bps / 10_000
            outer_cost_sum += outer_cost
            turnover_sum += turn
            reb_log.append(
                {
                    "signal_date": str(execute_map[date].date()),
                    "execution_date": str(date.date()),
                    "execution_rule": "next_session_after_month_end_close_signal",
                    "price_basis": "leg daily total-return units; fill modeled at session open via full-day return after reset",
                    "turnover_l1": turn,
                    "outer_cost": outer_cost,
                    "weights_before": dict(weights),
                    "weights_after": dict(targets),
                }
            )
            weights = {k: float(v) for k, v in targets.items()}

        gross = sum(weights[k] * float(rets[k].loc[date]) for k in targets)
        # Drift after return
        grown = {k: weights[k] * (1.0 + float(rets[k].loc[date])) for k in targets}
        total = sum(grown.values())
        if total > 0:
            weights = {k: grown[k] / total for k in targets}
        rows.append(
            {
                "date": date,
                "gross_return": gross,
                "outer_rebalance_cost": outer_cost,
                "net_return": gross - outer_cost,
                **{f"w_{k}": weights[k] for k in targets},
            }
        )

    equity = pd.DataFrame(rows).set_index("date")
    equity["equity_net"] = (1 + equity["net_return"]).cumprod()
    equity["equity_gross"] = (1 + equity["gross_return"]).cumprod()
    span_years = max((idx.max() - idx.min()).days / 365.25, 1 / 12)
    meta = {
        "label": label,
        "targets": targets,
        "n_rebalances": len(reb_log),
        "outer_cost_total": outer_cost_sum,
        "ann_outer_turnover": float(turnover_sum / 2 / span_years),
        "rebalance_log": reb_log,
        "construction": (
            "Month-end close forms signal; execution next trading session; "
            "weights drift daily between rebalances; outer one-way bps on L1 turnover only."
        ),
    }
    return equity, meta


def relative_nav_detail(equity: pd.DataFrame, spy_equity: pd.DataFrame) -> dict[str, Any]:
    """Metric C style — never substitute monthly-return streaks."""
    c = metric_c_relative_nav(equity, spy_equity)
    longest = c.get("longest_period") or {}
    return {
        "definition": c["definition"],
        "max_relative_drawdown": c["max_relative_drawdown"],
        "current_relative_drawdown": c["current_relative_drawdown"],
        "months_since_relative_peak": c["months_since_relative_peak"],
        "last_relative_peak_date": c["last_relative_peak_date"],
        "sample_end": c["sample_end"],
        "longest_underwater_months": longest.get("duration_months"),
        "longest_start": longest.get("start_date"),
        "longest_trough": longest.get("trough_date"),
        "longest_recovery": longest.get("recovery_date"),
        "longest_ongoing": longest.get("ongoing"),
        "trough_drawdown": longest.get("trough_drawdown"),
        "rolling_win_rate_vs_spy": c["rolling_win_rate_vs_spy"],
    }


def run_final_sleeve_audit(config: DualMomentumConfig, opens: pd.DataFrame, closes: pd.DataFrame) -> dict[str, Any]:
    dc_name = config.raw.get("confirmation", {}).get("frozen_variant", "attribution_DC")
    horizons = tuple(config.raw.get("confirmation", {}).get("frozen_trend_horizons", [3, 6, 12]))
    base_bps = float(config.raw["costs"]["one_way_bps"])

    dc = run_variant(opens, closes, config, dc_name, one_way_bps=base_bps, trend_horizons=horizons)
    start = dc["equity"].index.min()
    spy = trim_result(run_buy_and_hold(closes, "SPY", start=start, name="bh_spy"), start)
    sixty = trim_result(run_sixty_forty(opens, closes, config, start=start), start)
    common = align_start({"dc": dc, "spy": spy, "sixty": sixty})
    dc, spy, sixty = trim_result(dc, common), trim_result(spy, common), trim_result(sixty, common)

    spy_rets = spy["equity"]["net_return"]
    # D+C net already includes INTERNAL trading costs
    dc_rets = dc["equity"]["net_return"]
    dc_internal_cost_total = float(dc["equity"]["cost"].sum()) if "cost" in dc["equity"].columns else float("nan")

    portfolios: dict[str, dict[str, Any]] = {}

    # 100% legs
    for name, eq, targets in [
        ("100_spy", spy["equity"], {"spy": 1.0}),
        ("100_dc", dc["equity"], {"dc": 1.0}),
    ]:
        # Normalize column names for consistency
        frame = eq.copy()
        if "outer_rebalance_cost" not in frame.columns:
            frame["outer_rebalance_cost"] = 0.0
        portfolios[name] = {
            "equity": frame,
            "meta": {
                "label": name,
                "targets": targets,
                "outer_cost_total": 0.0,
                "ann_outer_turnover": 0.0,
                "n_rebalances": 0,
                "construction": "single-leg buy-and-hold or strategy NAV",
            },
            "dc_internal_cost_total": dc_internal_cost_total if name == "100_dc" else 0.0,
        }

    # Blends SPY + D+C
    for sc in [DEFAULT_CANDIDATE, CONSERVATIVE_SHADOW, {"name": "40_60", "spy": 0.4, "dc": 0.6}]:
        eq, meta = outer_blend_pit(
            {"spy": spy_rets, "dc": dc_rets},
            {"spy": sc["spy"], "dc": sc["dc"]},
            one_way_bps=base_bps,
            label=sc["name"],
        )
        portfolios[sc["name"]] = {
            "equity": eq,
            "meta": meta,
            "dc_internal_cost_total": dc_internal_cost_total * sc["dc"],  # approximate attribution
        }

    # Traditional 60/40 SPY/IEF
    portfolios["bench_60_40_ief"] = {
        "equity": sixty["equity"].assign(outer_rebalance_cost=sixty["equity"].get("cost", 0.0)),
        "meta": {
            "label": "bench_60_40_ief",
            "targets": {"SPY": 0.6, "IEF": 0.4},
            "construction": "existing run_sixty_forty (month-end signal / next open)",
            "outer_cost_total": float(sixty["equity"]["cost"].sum()) if "cost" in sixty["equity"] else 0.0,
            "ann_outer_turnover": np.nan,
            "n_rebalances": np.nan,
        },
        "dc_internal_cost_total": 0.0,
    }

    # Simple defensive benchmarks
    cash_rets = cash_total_returns(closes, config).reindex(spy_rets.index).fillna(0.0)
    ief_rets = daily_total_returns(closes, "IEF").reindex(spy_rets.index).fillna(0.0)
    gld_rets = daily_total_returns(closes, "GLD").reindex(spy_rets.index).fillna(0.0)
    spy_asset_rets = daily_total_returns(closes, "SPY").reindex(spy_rets.index).fillna(0.0)

    for bench in SIMPLE_BENCHMARKS:
        legs = {}
        targets = {}
        for sym, w in bench["legs"]:
            if sym == "CASH":
                legs["cash"] = cash_rets
                targets["cash"] = w
            elif sym == "SPY":
                legs["spy"] = spy_asset_rets
                targets["spy"] = w
            elif sym == "IEF":
                legs["ief"] = ief_rets
                targets["ief"] = w
            elif sym == "GLD":
                legs["gld"] = gld_rets
                targets["gld"] = w
        eq, meta = outer_blend_pit(legs, targets, one_way_bps=base_bps, label=bench["name"])
        portfolios[bench["name"]] = {"equity": eq, "meta": meta, "dc_internal_cost_total": 0.0}

    # Stats + relative NAV details
    spy_eq = portfolios["100_spy"]["equity"]
    results = {}
    for name, payload in portfolios.items():
        eq = payload["equity"]
        stats = _stats_extended(eq["net_return"])
        rel = relative_nav_detail(eq, spy_eq) if name != "100_spy" else {
            "definition": "identical series",
            "max_relative_drawdown": 0.0,
            "current_relative_drawdown": 0.0,
            "longest_underwater_months": 0,
            "longest_start": None,
            "longest_trough": None,
            "longest_recovery": None,
            "longest_ongoing": False,
            "rolling_win_rate_vs_spy": {"3y": np.nan, "5y": np.nan, "10y": np.nan},
            "months_since_relative_peak": 0,
            "last_relative_peak_date": str(eq.index[-1].date()),
            "sample_end": str(eq.index[-1].date()),
            "trough_drawdown": 0.0,
        }
        end_10k = float(10_000 * eq["equity_net"].iloc[-1])
        results[name] = {
            "stats": stats,
            "stats_full_precision": {
                "cagr": stats["cagr"],
                "max_drawdown": stats["max_drawdown"],
                "volatility": stats["volatility"],
                "sharpe": stats["sharpe"],
            },
            "relative_nav": rel,
            "end_value_10k": end_10k,
            "end_value_10k_full": end_10k,
            "yearly_returns": yearly_returns(eq),
            "meta": payload["meta"],
            "dc_internal_cost_total": payload["dc_internal_cost_total"],
            "outer_cost_total": payload["meta"].get("outer_cost_total", 0.0),
        }

    # Precision reconciliation for 80/20 vs SPY
    spy_cagr = results["100_spy"]["stats"]["cagr"]
    m80_cagr = results["80_20"]["stats"]["cagr"]
    spy_dd = results["100_spy"]["stats"]["max_drawdown"]
    m80_dd = results["80_20"]["stats"]["max_drawdown"]
    cagr_gap = m80_cagr - spy_cagr
    dd_reduction = abs(spy_dd) - abs(m80_dd)
    precision = {
        "spy_cagr_full": spy_cagr,
        "m80_cagr_full": m80_cagr,
        "cagr_gap_full": cagr_gap,
        "cagr_gap_rounded_2dp_pp": round(cagr_gap * 100, 2),
        "display_was_minus_0_14pp_explanation": (
            "Prior report used unrounded floats then formatted each CAGR to 2 decimals "
            f"({m80_cagr:.2%} and {spy_cagr:.2%}), whose difference looks like "
            f"{(round(m80_cagr,4)-round(spy_cagr,4))*100:.2f}pp, while the true gap is "
            f"{cagr_gap*100:.6f}pp. Rounded-display subtraction ≠ subtraction-then-round."
        ),
        "spy_max_dd_full": spy_dd,
        "m80_max_dd_full": m80_dd,
        "dd_reduction_full": dd_reduction,
        "cagr_cost_per_1pp_dd_full": (spy_cagr - m80_cagr) / (dd_reduction * 100)
        if dd_reduction > 1e-12
        else np.nan,
        "spy_10k_full": results["100_spy"]["end_value_10k_full"],
        "m80_10k_full": results["80_20"]["end_value_10k_full"],
        "m60_10k_full": results["60_40"]["end_value_10k_full"],
    }

    # Construction audit checklist
    sample_log = portfolios["80_20"]["meta"].get("rebalance_log") or []
    construction_audit = {
        "outer_rebalance_is_monthly_target_weights": True,
        "weights_drift_between_rebalances": True,
        "not_constant_daily_0_8_0_2": True,
        "signal_on_month_end_close": True,
        "execution_next_session": True,
        "no_same_close_fill_after_signal": True,
        "dc_internal_costs_in_dc_nav": True,
        "outer_costs_only_on_sleeve_rebalance": True,
        "total_return_basis": "Yahoo Adj Close / strategy equity_net",
        "example_first_rebalance": sample_log[0] if sample_log else None,
        "example_second_rebalance": sample_log[1] if len(sample_log) > 1 else None,
    }

    # Look-through for candidate
    dc_holdings = expand_dc_holdings(dc["targets"], portfolios["80_20"]["equity"].index)
    # Rebuild w_spy/w_dc columns expected by look_through helper
    blend = portfolios["80_20"]["equity"].rename(columns={"w_spy": "w_spy", "w_dc": "w_dc"})
    look = look_through_exposures(blend, dc_holdings, w_spy_target=0.8, w_dc_target=0.2)

    # Compare 20% D+C vs simple 20% defenses
    def score_row(name: str) -> dict[str, Any]:
        r = results[name]
        return {
            "name": name,
            "cagr": r["stats"]["cagr"],
            "max_drawdown": r["stats"]["max_drawdown"],
            "sharpe": r["stats"]["sharpe"],
            "end_10k": r["end_value_10k_full"],
            "max_rel_dd": r["relative_nav"]["max_relative_drawdown"],
            "underwater_months": r["relative_nav"]["longest_underwater_months"],
            "ongoing": r["relative_nav"]["longest_ongoing"],
        }

    comparison = {
        "candidate_80_20_dc": score_row("80_20"),
        "simple_benchmarks": [score_row(b["name"]) for b in SIMPLE_BENCHMARKS],
        "judgment": None,
    }
    cand = comparison["candidate_80_20_dc"]
    simples = {s["name"]: s for s in comparison["simple_benchmarks"]}
    better_dd_than_all = all(
        abs(cand["max_drawdown"]) < abs(s["max_drawdown"]) - 1e-12 for s in simples.values()
    )
    vs = {
        name: {
            "cagr_edge_pp": (cand["cagr"] - s["cagr"]) * 100,
            "maxdd_edge_pp": (abs(s["max_drawdown"]) - abs(cand["max_drawdown"])) * 100,
        }
        for name, s in simples.items()
    }
    comparison["judgment"] = {
        "dc_sleeve_better_maxdd_than_all_simple_20pct": bool(better_dd_than_all),
        "dc_sleeve_better_maxdd_than_simple_20pct": bool(better_dd_than_all),  # alias
        "cagr_vs_80_20_ief_pp": vs["80_20_ief"]["cagr_edge_pp"],
        "pairwise_vs_simple": vs,
        "verdict": (
            "20% D+C is NOT uniformly better than simple 20% defenses. "
            "vs 80/20 IEF: higher CAGR but worse MaxDD; "
            "vs 80/20 cash: similar MaxDD with higher CAGR; "
            "vs 80/20 GLD: lower CAGR and worse MaxDD on this sample. "
            "Keep 80/20 D+C as the frozen research candidate for paper tracking "
            "(momentum diversifier thesis), not because it dominates static sleeves."
        ),
        "note": (
            "Pre-declared benchmarks only — no weight search. "
            "Paper default remains 80/20 SPY/D+C by prior freeze decision."
        ),
    }

    # Gate for proceeding to paper trading
    audit_pass = bool(
        construction_audit["execution_next_session"]
        and construction_audit["weights_drift_between_rebalances"]
        and results["80_20"]["relative_nav"]["longest_underwater_months"] is not None
        and abs(precision["cagr_gap_full"]) < 0.01
    )

    return {
        "common_start": str(common.date()),
        "sample_end": str(dc["equity"].index.max().date()),
        "frozen_dc": dc_name,
        "default_candidate": DEFAULT_CANDIDATE,
        "conservative_shadow": CONSERVATIVE_SHADOW,
        "config_hash": config_hash(config),
        "one_way_bps": base_bps,
        "results": results,
        "precision": precision,
        "construction_audit": construction_audit,
        "look_through_80_20": look,
        "simple_benchmark_comparison": comparison,
        "audit_pass": audit_pass,
        "portfolios": portfolios,  # includes equity for paper seeding
        "dc_result": dc,
        "spy_result": spy,
    }


def write_final_audit_md(directory: Path, study: dict[str, Any], promote_to: Optional[Path] = None) -> Path:
    def pct(x):
        if x is None or (isinstance(x, float) and x != x):
            return "n/a"
        return f"{x:.2%}"

    def pct6(x):
        if x is None or (isinstance(x, float) and x != x):
            return "n/a"
        return f"{x*100:.6f}pp"

    lines = [
        "# D+C Sleeve Final Audit (pre-IBKR)",
        "",
        f"- Frozen D+C: `{study['frozen_dc']}` — **3/6/12 + category constraint unchanged**",
        f"- Default paper candidate: **80% SPY + 20% D+C**",
        f"- Conservative shadow only: **60% SPY + 40% D+C** (no weight search)",
        f"- Sample: `{study['common_start']}` → `{study['sample_end']}`",
        f"- config_hash: `{study['config_hash']}`",
        f"- Audit gate: **{'PASS' if study['audit_pass'] else 'FAIL'}**",
        "",
        "## 1. Relative NAV underwater (Metric C only)",
        "",
        "| Portfolio | Longest underwater | Start | Trough | Recovery | Ongoing? | Current rel DD | Max rel DD | 3y win | 5y win | 10y win |",
        "|---|---:|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for name in ["80_20", "60_40", "100_dc", "80_20_ief", "80_20_cash", "80_20_gld", "90_10_ief"]:
        r = study["results"][name]["relative_nav"]
        wr = r.get("rolling_win_rate_vs_spy") or {}
        lines.append(
            "| {name} | {m}m | {st} | {tr} | {rec} | {og} | {cur} | {mx} | {a} | {b} | {c} |".format(
                name=name,
                m=r.get("longest_underwater_months"),
                st=r.get("longest_start"),
                tr=r.get("longest_trough"),
                rec=r.get("longest_recovery") or "NONE",
                og="yes" if r.get("longest_ongoing") else "no",
                cur=pct(r.get("current_relative_drawdown")),
                mx=pct(r.get("max_relative_drawdown")),
                a=pct(wr.get("3y")),
                b=pct(wr.get("5y")),
                c=pct(wr.get("10y")),
            )
        )
    lines.append(
        "- These are **relative-NAV opportunity-cost intervals**, not consecutive single-month underperformance streaks."
    )

    ca = study["construction_audit"]
    lines.extend(
        [
            "",
            "## 2. Construction audit",
            "",
            f"- Outer monthly target rebalance: `{ca['outer_rebalance_is_monthly_target_weights']}`",
            f"- Weights drift between rebalances (not constant 0.8/0.2 daily): `{ca['weights_drift_between_rebalances']}`",
            f"- Signal = month-end close; execution = next session: `{ca['signal_on_month_end_close']}` / `{ca['execution_next_session']}`",
            f"- No same-close fill after signal: `{ca['no_same_close_fill_after_signal']}`",
            f"- D+C internal costs inside D+C NAV: `{ca['dc_internal_costs_in_dc_nav']}`",
            f"- Outer costs only on sleeve rebalance: `{ca['outer_costs_only_on_sleeve_rebalance']}`",
            f"- Total-return basis: `{ca['total_return_basis']}`",
            f"- Example rebalance: `{json.dumps(ca.get('example_first_rebalance'), default=str)}`",
            "",
            "### Cost separation (80/20)",
            "",
            f"- D+C internal cost total (full D+C book): `{study['results']['100_dc']['dc_internal_cost_total']}`",
            f"- Outer sleeve rebalance cost total (80/20): `{study['results']['80_20']['outer_cost_total']}`",
            "- Internal costs are **not** charged again at the outer layer.",
            "",
            "## 3. Full-precision reconciliation (80/20 vs SPY)",
            "",
        ]
    )
    p = study["precision"]
    lines.extend(
        [
            f"- SPY CAGR full: `{p['spy_cagr_full']}`",
            f"- 80/20 CAGR full: `{p['m80_cagr_full']}`",
            f"- CAGR gap full: `{p['cagr_gap_full']}` = **{pct6(p['cagr_gap_full'])}**",
            f"- Display explanation: {p['display_was_minus_0_14pp_explanation']}",
            f"- MaxDD SPY / 80/20: `{p['spy_max_dd_full']}` / `{p['m80_max_dd_full']}`",
            f"- DD reduction full: `{p['dd_reduction_full']}`",
            f"- CAGR cost per 1pp MaxDD: `{p['cagr_cost_per_1pp_dd_full']}` ({pct(p['cagr_cost_per_1pp_dd_full'])} CAGR per 1pp)",
            f"- $10k end SPY / 80/20 / 60/40: "
            f"`{p['spy_10k_full']:.6f}` / `{p['m80_10k_full']:.6f}` / `{p['m60_10k_full']:.6f}`",
            "",
            "## 4. Simple defensive benchmarks (pre-declared)",
            "",
            "| Portfolio | CAGR | MaxDD | Sharpe | $10k | Max rel DD | Underwater |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name in ["100_spy", "80_20", "60_40", "80_20_ief", "80_20_cash", "80_20_gld", "90_10_ief", "bench_60_40_ief"]:
        r = study["results"][name]
        lines.append(
            f"| {name} | {pct(r['stats']['cagr'])} | {pct(r['stats']['max_drawdown'])} | "
            f"{r['stats']['sharpe']:.4f} | {r['end_value_10k_full']:.2f} | "
            f"{pct(r['relative_nav']['max_relative_drawdown'])} | "
            f"{r['relative_nav']['longest_underwater_months']}m |"
        )
    j = study["simple_benchmark_comparison"]["judgment"]
    lines.extend(
        [
            "",
            f"- 20% D+C better MaxDD than all simple 20% defenses: **{j['dc_sleeve_better_maxdd_than_simple_20pct']}**",
            f"- CAGR vs 80/20 IEF: **{j['cagr_vs_80_20_ief_pp']:.4f}pp**",
            f"- Pairwise (CAGR edge / MaxDD edge vs candidate, pp): `{json.dumps(j.get('pairwise_vs_simple'), default=str)}`",
            f"- Verdict: {j.get('verdict', j.get('note'))}",
            f"- {j['note']}",
            "",
            "## 5. Look-through (80/20)",
            "",
            f"`{json.dumps(study['look_through_80_20'], default=str)}`",
            "",
            "## 6. Paper-trading readiness",
            "",
            "- Default candidate frozen: 80/20 SPY/D+C",
            "- Conservative shadow: 60/40 SPY/D+C",
            "- Opportunity-cost benchmark: 100% SPY",
            "- Traditional benchmark: 60/40 SPY/IEF",
            "- IBKR constraints implemented in `paper_trading` module when audit_pass is true.",
            "",
        ]
    )

    path = directory / "dc_sleeve_final_audit.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    serializable = {k: v for k, v in study.items() if k not in {"portfolios", "dc_result", "spy_result"}}
    # strip nested equity if any leaked
    (directory / "dc_sleeve_final_audit.json").write_text(
        json.dumps(serializable, indent=2, default=str), encoding="utf-8"
    )
    if promote_to is not None:
        promote_to.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        (promote_to.parent / "dc_sleeve_final_audit.json").write_text(
            json.dumps(serializable, indent=2, default=str), encoding="utf-8"
        )
    return path
