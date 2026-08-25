"""Evaluate D+C as a defensive sleeve around SPY (pre-declared weights only)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from .artifacts import config_hash, new_run_directory
from .attribution import (
    align_start,
    run_buy_and_hold,
    run_sixty_forty,
    trim_result,
    window_total_return,
)
from .backtest import run_variant
from .config import DualMomentumConfig
from .data import load_ohlc
from .relative_spy_audit import build_relative_nav, metric_c_relative_nav
from .signals import month_end_index


# Pre-declared scenarios — do NOT optimize by Sharpe.
SLEEVE_SCENARIOS = [
    {"name": "100_spy", "spy": 1.0, "dc": 0.0},
    {"name": "100_dc", "spy": 0.0, "dc": 1.0},
    {"name": "80_20", "spy": 0.8, "dc": 0.2},
    {"name": "60_40", "spy": 0.6, "dc": 0.4},
    {"name": "40_60", "spy": 0.4, "dc": 0.6},
]

ASSET_BUCKET = {
    "SPY": "equity",
    "QQQ": "equity",
    "IWM": "equity",
    "VEA": "equity",
    "VWO": "equity",
    "IEF": "bond",
    "GLD": "gold",
    "SGOV": "cash",
    "BIL": "cash",
}

STRESS = {
    "dotcom_2000_2002": ("2000-01-01", "2002-12-31"),
    "gfc_2008": ("2007-10-01", "2009-03-31"),
    "covid_2020": ("2020-02-01", "2020-04-30"),
    "bear_2022": ("2022-01-01", "2022-12-31"),
}


def _stats_extended(returns: pd.Series) -> dict[str, float]:
    returns = returns.dropna()
    if returns.empty:
        return {
            "cagr": np.nan,
            "volatility": np.nan,
            "sharpe": np.nan,
            "sortino": np.nan,
            "max_drawdown": np.nan,
            "calmar": np.nan,
            "worst_12m": np.nan,
            "worst_36m": np.nan,
        }
    equity = (1 + returns).cumprod()
    years = len(returns) / 252.0
    vol = float(returns.std(ddof=1) * np.sqrt(252)) if len(returns) > 1 else np.nan
    cagr = float(equity.iloc[-1] ** (1 / years) - 1) if years > 0 else np.nan
    downside = returns.clip(upper=0.0)
    down_std = float(downside.std(ddof=1) * np.sqrt(252)) if len(returns) > 1 else np.nan
    sharpe = float(returns.mean() / returns.std(ddof=1) * np.sqrt(252)) if returns.std(ddof=1) else np.nan
    sortino = float(returns.mean() / downside.std(ddof=1) * np.sqrt(252)) if downside.std(ddof=1) else np.nan
    max_dd = float((equity / equity.cummax() - 1).min())
    calmar = float(cagr / abs(max_dd)) if max_dd and np.isfinite(max_dd) and max_dd != 0 else np.nan
    return {
        "cagr": cagr,
        "volatility": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "worst_12m": _worst_trailing(returns, 252),
        "worst_36m": _worst_trailing(returns, 252 * 3),
    }


def _worst_trailing(returns: pd.Series, window: int) -> float:
    if len(returns) < window:
        return float((1 + returns).prod() - 1) if len(returns) else np.nan
    trail = (1 + returns).rolling(window).apply(np.prod, raw=True) - 1
    return float(trail.min())


def _month_ends(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return month_end_index(index)


def _year_ends(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(index).sort_values()
    frame = pd.DataFrame({"date": idx})
    ends = frame.groupby(frame["date"].dt.to_period("Y"), sort=True)["date"].max()
    return pd.DatetimeIndex(ends.to_numpy())


def blend_portfolios(
    spy_rets: pd.Series,
    dc_rets: pd.Series,
    *,
    w_spy: float,
    w_dc: float,
    rebalance: str = "month",
    one_way_bps: float = 5.0,
) -> tuple[pd.DataFrame, float]:
    """
    Blend SPY BH and D+C daily returns with fixed target weights.
    Rebalance at month-end or year-end after that day's returns (weights drift intraday,
    then reset); sleeve rebalance pays one-way bps on L1 weight change.
    """
    idx = spy_rets.index.intersection(dc_rets.index).sort_values()
    spy_rets = spy_rets.reindex(idx).fillna(0.0)
    dc_rets = dc_rets.reindex(idx).fillna(0.0)
    if rebalance == "month":
        reb_dates = set(_month_ends(idx))
    elif rebalance == "year":
        reb_dates = set(_year_ends(idx))
    else:
        raise ValueError(rebalance)

    w_s, w_d = float(w_spy), float(w_dc)
    rows = []
    turnover_sum = 0.0
    for date in idx:
        r_s = float(spy_rets.loc[date])
        r_d = float(dc_rets.loc[date])
        r = w_s * r_s + w_d * r_d
        cost = 0.0
        gro_s = w_s * (1.0 + r_s)
        gro_d = w_d * (1.0 + r_d)
        total = gro_s + gro_d
        if total > 0:
            w_s, w_d = gro_s / total, gro_d / total
        if date in reb_dates:
            turn = abs(w_spy - w_s) + abs(w_dc - w_d)
            cost = turn * one_way_bps / 10_000
            turnover_sum += turn
            w_s, w_d = float(w_spy), float(w_dc)
        rows.append(
            {
                "date": date,
                "gross_return": r,
                "cost": cost,
                "net_return": r - cost,
                "w_spy": w_s,
                "w_dc": w_d,
            }
        )
    equity = pd.DataFrame(rows).set_index("date")
    equity["equity_net"] = (1 + equity["net_return"]).cumprod()
    equity["equity_gross"] = (1 + equity["gross_return"]).cumprod()
    span_years = max((idx.max() - idx.min()).days / 365.25, 1 / 12)
    ann_to = float(turnover_sum / 2 / span_years)
    return equity, ann_to


def expand_dc_holdings(targets: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Forward-fill D+C target weights onto daily index (by execution_date).

    Missing symbols on a rebalance date are explicitly zeroed so departed names
    do not linger via ffill.
    """
    if targets.empty:
        return pd.DataFrame(0.0, index=index, columns=[])
    t = targets.copy()
    t["execution_date"] = pd.to_datetime(t["execution_date"])
    symbols = sorted(t["symbol"].astype(str).unique())
    pivot = (
        t.pivot_table(index="execution_date", columns="symbol", values="weight", aggfunc="sum")
        .reindex(columns=symbols)
        .sort_index()
        .fillna(0.0)
    )
    # Ensure each rebalance row is a complete weight vector (zeros for absent names)
    daily = pivot.reindex(index.union(pivot.index)).sort_index()
    # On non-rebalance days NaN → ffill; rebalance days already 0-filled
    daily = daily.ffill().reindex(index).fillna(0.0)
    return daily


def look_through_exposures(
    blend_equity: pd.DataFrame,
    dc_holdings: pd.DataFrame,
    *,
    w_spy_target: float,
    w_dc_target: float,
) -> dict[str, float]:
    """Average look-through bucket weights using drifted outer weights × D+C internals + outer SPY."""
    idx = blend_equity.index.intersection(dc_holdings.index)
    if len(idx) == 0:
        return {b: np.nan for b in ("equity", "bond", "gold", "cash")}
    w_s = blend_equity.loc[idx, "w_spy"]
    w_d = blend_equity.loc[idx, "w_dc"]
    # Outer SPY is pure equity
    buckets = {b: pd.Series(0.0, index=idx) for b in ("equity", "bond", "gold", "cash")}
    buckets["equity"] = buckets["equity"] + w_s
    for symbol in dc_holdings.columns:
        bucket = ASSET_BUCKET.get(symbol, "equity")
        if bucket not in buckets:
            continue
        buckets[bucket] = buckets[bucket] + w_d * dc_holdings.loc[idx, symbol].fillna(0.0)
    # Overlap diagnostics
    dc_spy = dc_holdings["SPY"] if "SPY" in dc_holdings.columns else pd.Series(0.0, index=idx)
    dc_qqq = dc_holdings["QQQ"] if "QQQ" in dc_holdings.columns else pd.Series(0.0, index=idx)
    lookthrough_spy = w_s + w_d * dc_spy.reindex(idx).fillna(0.0)
    lookthrough_qqq = w_d * dc_qqq.reindex(idx).fillna(0.0)
    return {
        "avg_equity": float(buckets["equity"].mean()),
        "avg_bond": float(buckets["bond"].mean()),
        "avg_gold": float(buckets["gold"].mean()),
        "avg_cash": float(buckets["cash"].mean()),
        "avg_lookthrough_SPY": float(lookthrough_spy.mean()),
        "avg_lookthrough_QQQ": float(lookthrough_qqq.mean()),
        "avg_lookthrough_US_equity_overlap": float((lookthrough_spy + lookthrough_qqq).mean()),
        "max_lookthrough_SPY": float(lookthrough_spy.max()),
        "target_outer_spy": w_spy_target,
        "target_outer_dc": w_dc_target,
    }


def yearly_returns(equity: pd.DataFrame) -> dict[str, float]:
    r = equity["net_return"]
    out = (1 + r).groupby(r.index.year).prod() - 1
    return {str(k): float(v) for k, v in out.items()}


def rolling_beat_spy(equity: pd.DataFrame, spy_equity: pd.DataFrame) -> dict[str, float]:
    frame = build_relative_nav(equity, spy_equity)
    month_end = frame.groupby(frame.index.to_period("M")).tail(1)
    rates = {}
    for years, label in [(3, "3y"), (5, "5y"), (10, "10y")]:
        lag = years * 12
        nav_p = month_end["nav_dc"]
        nav_s = month_end["nav_spy"]
        if len(nav_p) <= lag:
            rates[label] = float("nan")
            continue
        rp = nav_p / nav_p.shift(lag) - 1
        rs = nav_s / nav_s.shift(lag) - 1
        cmp = pd.concat([rp.rename("p"), rs.rename("s")], axis=1).dropna()
        rates[label] = float((cmp["p"] > cmp["s"]).mean()) if len(cmp) else float("nan")
    return rates


def relative_vs_spy_summary(equity: pd.DataFrame, spy_equity: pd.DataFrame) -> dict[str, Any]:
    c = metric_c_relative_nav(equity, spy_equity)
    longest = c.get("longest_period") or {}
    return {
        "max_relative_drawdown": c["max_relative_drawdown"],
        "current_relative_drawdown": c["current_relative_drawdown"],
        "longest_underwater_months": longest.get("duration_months"),
        "longest_underwater_ongoing": longest.get("ongoing"),
        "longest_start": longest.get("start_date"),
        "longest_trough": longest.get("trough_date"),
        "longest_recovery": longest.get("recovery_date"),
        "months_since_peak": c["months_since_relative_peak"],
        "rolling_win_rate": c["rolling_win_rate_vs_spy"],
    }


def evaluate_scenario(
    name: str,
    w_spy: float,
    w_dc: float,
    spy_rets: pd.Series,
    dc_rets: pd.Series,
    spy_equity: pd.DataFrame,
    dc_holdings: pd.DataFrame,
    *,
    one_way_bps: float,
    rebalance: str,
) -> dict[str, Any]:
    equity, ann_to = blend_portfolios(
        spy_rets, dc_rets, w_spy=w_spy, w_dc=w_dc, rebalance=rebalance, one_way_bps=one_way_bps
    )
    stats = _stats_extended(equity["net_return"])
    rel = relative_vs_spy_summary(equity, spy_equity)
    look = look_through_exposures(equity, dc_holdings, w_spy_target=w_spy, w_dc_target=w_dc)
    stress = {}
    for label, (a, b) in STRESS.items():
        if equity.index.min() > pd.Timestamp(b) or equity.index.max() < pd.Timestamp(a):
            stress[label] = None  # unavailable
        else:
            stress[label] = window_total_return(equity, a, b)
    end_value = float(10_000 * equity["equity_net"].iloc[-1]) if len(equity) else np.nan
    return {
        "name": name,
        "w_spy": w_spy,
        "w_dc": w_dc,
        "rebalance": rebalance,
        "one_way_bps": one_way_bps,
        "stats": stats,
        "relative_vs_spy": rel,
        "look_through": look,
        "stress": stress,
        "yearly_returns": yearly_returns(equity),
        "end_value_10k": end_value,
        "ann_turnover": ann_to,
        "equity": equity,
    }


def tradeoff_vs_spy(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = next(s for s in scenarios if s["name"] == "100_spy")
    base_cagr = base["stats"]["cagr"]
    base_dd = base["stats"]["max_drawdown"]
    rows = []
    for s in scenarios:
        dd_improve = float(base_dd - s["stats"]["max_drawdown"])  # less negative => positive improve in magnitude?
        # MaxDD are negative; improvement in drawdown = base_dd - mix_dd (e.g. -0.55 - (-0.40) = -0.15) wrong
        # User wants: how much MaxDD improved (reduction in |DD|) and CAGR sacrificed
        dd_reduction = float(abs(base_dd) - abs(s["stats"]["max_drawdown"]))  # positive = better DD
        cagr_sacrifice = float(base_cagr - s["stats"]["cagr"])  # positive = gave up CAGR
        cost_per_dd_pp = (
            float(cagr_sacrifice / (dd_reduction * 100)) if dd_reduction > 1e-6 else np.nan
        )  # decimal CAGR per 1 percentage-point of |MaxDD|
        rows.append(
            {
                "name": s["name"],
                "cagr": s["stats"]["cagr"],
                "max_drawdown": s["stats"]["max_drawdown"],
                "dd_reduction_vs_spy": dd_reduction,
                "cagr_sacrifice_vs_spy": cagr_sacrifice,
                "cagr_cost_per_1pp_dd": cost_per_dd_pp,
            }
        )
    return rows


def run_sleeve_evaluation(
    config: DualMomentumConfig,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
) -> dict[str, Any]:
    dc_name = config.raw.get("confirmation", {}).get("frozen_variant", "attribution_DC")
    horizons = tuple(config.raw.get("confirmation", {}).get("frozen_trend_horizons", [3, 6, 12]))
    base_bps = float(config.raw["costs"]["one_way_bps"])

    dc = run_variant(opens, closes, config, dc_name, one_way_bps=base_bps, trend_horizons=horizons)
    start = dc["equity"].index.min()
    spy = trim_result(run_buy_and_hold(closes, "SPY", start=start, name="bh_spy"), start)
    sixty = trim_result(run_sixty_forty(opens, closes, config, start=start), start)
    common = align_start({"dc": dc, "spy": spy, "sixty": sixty})
    dc = trim_result(dc, common)
    spy = trim_result(spy, common)
    sixty = trim_result(sixty, common)

    spy_rets = spy["equity"]["net_return"]
    dc_rets = dc["equity"]["net_return"]
    dc_holdings = expand_dc_holdings(dc["targets"], dc["equity"].index)

    monthly = []
    for sc in SLEEVE_SCENARIOS:
        monthly.append(
            evaluate_scenario(
                sc["name"],
                sc["spy"],
                sc["dc"],
                spy_rets,
                dc_rets,
                spy["equity"],
                dc_holdings,
                one_way_bps=base_bps,
                rebalance="month",
            )
        )
    # 60/40 benchmark as external
    sixty_stats = _stats_extended(sixty["equity"]["net_return"])
    sixty_row = {
        "name": "bench_60_40",
        "w_spy": 0.6,
        "w_dc": 0.0,
        "rebalance": "month",
        "one_way_bps": base_bps,
        "stats": sixty_stats,
        "relative_vs_spy": relative_vs_spy_summary(sixty["equity"], spy["equity"]),
        "look_through": {
            "avg_equity": 0.6,
            "avg_bond": 0.4,
            "avg_gold": 0.0,
            "avg_cash": 0.0,
            "note": "fixed 60% SPY + 40% IEF",
        },
        "stress": {
            k: (None if sixty["equity"].index.min() > pd.Timestamp(b) else window_total_return(sixty["equity"], a, b))
            for k, (a, b) in STRESS.items()
        },
        "yearly_returns": yearly_returns(sixty["equity"]),
        "end_value_10k": float(10_000 * sixty["equity"]["equity_net"].iloc[-1]),
        "ann_turnover": np.nan,
        "equity": sixty["equity"],
    }

    annual = []
    for sc in SLEEVE_SCENARIOS:
        annual.append(
            evaluate_scenario(
                sc["name"],
                sc["spy"],
                sc["dc"],
                spy_rets,
                dc_rets,
                spy["equity"],
                dc_holdings,
                one_way_bps=base_bps,
                rebalance="year",
            )
        )

    # Cost sensitivity on monthly blends of interest + endpoints
    cost_rows = []
    for bps in [5.0, 10.0, 20.0]:
        # Need DC at that cost
        dc_c = trim_result(
            run_variant(opens, closes, config, dc_name, one_way_bps=bps, trend_horizons=horizons),
            common,
        )
        for sc in SLEEVE_SCENARIOS:
            ev = evaluate_scenario(
                sc["name"],
                sc["spy"],
                sc["dc"],
                spy_rets,
                dc_c["equity"]["net_return"],
                spy["equity"],
                expand_dc_holdings(dc_c["targets"], dc_c["equity"].index),
                one_way_bps=bps,
                rebalance="month",
            )
            cost_rows.append(
                {
                    "bps": bps,
                    "name": sc["name"],
                    "cagr": ev["stats"]["cagr"],
                    "sharpe": ev["stats"]["sharpe"],
                    "max_drawdown": ev["stats"]["max_drawdown"],
                    "ann_turnover": ev["ann_turnover"],
                }
            )

    tradeoff = tradeoff_vs_spy(monthly)
    verdict = form_verdict(monthly, tradeoff)

    return {
        "common_start": str(common.date()),
        "sample_end": str(dc["equity"].index.max().date()),
        "frozen_dc": dc_name,
        "config_hash": config_hash(config),
        "monthly": monthly,
        "annual": annual,
        "bench_60_40": sixty_row,
        "cost_sensitivity": cost_rows,
        "tradeoff": tradeoff,
        "verdict": verdict,
        "turnover_month_vs_year": [
            {
                "name": m["name"],
                "month_ann_turnover": m["ann_turnover"],
                "year_ann_turnover": next(a["ann_turnover"] for a in annual if a["name"] == m["name"]),
            }
            for m in monthly
        ],
    }


def form_verdict(monthly: list[dict[str, Any]], tradeoff: list[dict[str, Any]]) -> dict[str, Any]:
    spy = next(s for s in monthly if s["name"] == "100_spy")
    dc = next(s for s in monthly if s["name"] == "100_dc")
    m20 = next(s for s in monthly if s["name"] == "80_20")
    m40 = next(s for s in monthly if s["name"] == "60_40")

    def dd_cut(s):
        return abs(spy["stats"]["max_drawdown"]) - abs(s["stats"]["max_drawdown"])

    def cagr_lag(s):
        return spy["stats"]["cagr"] - s["stats"]["cagr"]

    notes = []
    sleeve_ok = False
    for label, sc in [("20% D+C (80/20)", m20), ("40% D+C (60/40)", m40)]:
        cut = dd_cut(sc)
        lag = cagr_lag(sc)
        rel = sc["relative_vs_spy"]
        notes.append(
            f"{label}: MaxDD cut {cut:.2%} vs SPY; CAGR lag {lag:.2%}; "
            f"max rel-DD {rel.get('max_relative_drawdown'):.2%}; "
            f"rel underwater {rel.get('longest_underwater_months')}m "
            f"({'ongoing' if rel.get('longest_underwater_ongoing') else 'recovered'})"
        )
        # Modest sleeve: material DD cut, small CAGR drag, much shallower rel-DD than 100% DC
        if cut >= 0.05 and lag <= 0.01 and abs(rel.get("max_relative_drawdown") or 0) < 0.50:
            sleeve_ok = True

    dc_rel = abs(dc["relative_vs_spy"].get("max_relative_drawdown") or 0)
    m20_rel = abs(m20["relative_vs_spy"].get("max_relative_drawdown") or 0)
    m40_rel = abs(m40["relative_vs_spy"].get("max_relative_drawdown") or 0)

    # Growth mandate: reject if even modest sleeves still have deep relative DD like standalone DC
    severe_blend = m20_rel >= 0.35 and m40_rel >= 0.45
    terminal_close = cagr_lag(m20) <= 0.005  # within 50bps at 20% sleeve

    if sleeve_ok and terminal_close and not severe_blend:
        growth_ok = True
        reason = (
            "20%/40% D+C sleeves cut absolute MaxDD vs 100% SPY with only a small CAGR drag, "
            "and avoid 100% D+C's ~73% relative drawdown. "
            "Use as a **defensive overlay on a SPY core**, not as a replacement for SPY. "
            "Note: relative-NAV can remain underwater for long stretches after crisis relative peaks "
            f"(e.g. 80/20 max rel-DD {m20_rel:.1%}), so this is not a free lunch."
        )
    elif sleeve_ok:
        growth_ok = False
        reason = (
            "Sleeves reduce absolute MaxDD, but relative opportunity cost vs SPY remains "
            "material for a small-capital long-term growth mandate. Prefer SPY core; "
            "treat D+C only as an optional damper with eyes open to relative lag."
        )
    else:
        growth_ok = False
        reason = (
            "Pre-declared 20%/40% sleeves do not deliver a clean MaxDD vs CAGR tradeoff "
            "for the stated mandate."
        )

    return {
        "suitable_as_spy_defensive_sleeve": sleeve_ok,
        "suitable_for_small_capital_long_term_growth": growth_ok,
        "reason": reason,
        "notes": notes,
        "spy_max_dd": spy["stats"]["max_drawdown"],
        "dc_max_dd": dc["stats"]["max_drawdown"],
        "dc_rel_underwater_months": dc["relative_vs_spy"].get("longest_underwater_months"),
        "dc_max_relative_drawdown": dc["relative_vs_spy"].get("max_relative_drawdown"),
        "selection_rule": "Weights pre-declared; NOT chosen by max Sharpe.",
    }


def write_sleeve_report(directory: Path, study: dict[str, Any], promote_to: Optional[Path] = None) -> Path:
    def pct(x):
        if x is None or (isinstance(x, float) and x != x):
            return "n/a"
        return f"{x:.2%}"

    def num(x):
        if x is None or (isinstance(x, float) and x != x):
            return "n/a"
        return f"{x:.2f}"

    lines = [
        "# D+C as SPY Defensive Sleeve Evaluation",
        "",
        f"- Frozen D+C: `{study['frozen_dc']}` (rules unchanged)",
        f"- Sample: `{study['common_start']}` → `{study['sample_end']}`",
        f"- config_hash: `{study['config_hash']}`",
        "- Weights are **pre-declared scenarios**, not Sharpe-optimized.",
        "",
        f"## Verdict",
        "",
        f"- Suitable as SPY defensive sleeve (modest DD cut without extreme lag): "
        f"**{'YES' if study['verdict']['suitable_as_spy_defensive_sleeve'] else 'NO'}**",
        f"- Suitable for small-capital long-term growth core: "
        f"**{'YES' if study['verdict']['suitable_for_small_capital_long_term_growth'] else 'NO'}**",
        f"- {study['verdict']['reason']}",
        "",
    ]
    for n in study["verdict"]["notes"]:
        lines.append(f"- {n}")

    lines.extend(
        [
            "",
            "## Monthly rebalance — core metrics",
            "",
            "| Portfolio | CAGR | Vol | Sharpe | Sortino | MaxDD | Worst12M | Worst36M | Calmar | $10k end |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    rows = list(study["monthly"]) + [study["bench_60_40"]]
    labels = {
        "100_spy": "100% SPY",
        "100_dc": "100% D+C",
        "80_20": "80/20 SPY/D+C",
        "60_40": "60/40 SPY/D+C",
        "40_60": "40/60 SPY/D+C",
        "bench_60_40": "60/40 SPY/IEF",
    }
    for s in rows:
        st = s["stats"]
        lines.append(
            "| {name} | {cagr} | {vol} | {sh} | {so} | {dd} | {w12} | {w36} | {cal} | {end:.0f} |".format(
                name=labels.get(s["name"], s["name"]),
                cagr=pct(st["cagr"]),
                vol=pct(st["volatility"]),
                sh=num(st["sharpe"]),
                so=num(st["sortino"]),
                dd=pct(st["max_drawdown"]),
                w12=pct(st["worst_12m"]),
                w36=pct(st["worst_36m"]),
                cal=num(st["calmar"]),
                end=s["end_value_10k"],
            )
        )

    lines.extend(
        [
            "",
            "## vs 100% SPY — relative opportunity cost (Metric C style)",
            "",
            "| Portfolio | Max rel DD | Longest underwater | Ongoing? | 3y win | 5y win | 10y win |",
            "|---|---:|---:|---|---:|---:|---:|",
        ]
    )
    for s in study["monthly"]:
        r = s["relative_vs_spy"]
        wr = r.get("rolling_win_rate") or {}
        uw = r.get("longest_underwater_months")
        uw_s = "n/a" if uw is None else f"{uw}m"
        lines.append(
            f"| {labels[s['name']]} | {pct(r['max_relative_drawdown'])} | "
            f"{uw_s} | "
            f"{'yes' if r.get('longest_underwater_ongoing') else 'no'} | "
            f"{pct(wr.get('3y'))} | {pct(wr.get('5y'))} | {pct(wr.get('10y'))} |"
        )

    lines.extend(
        [
            "",
            "## MaxDD improvement vs CAGR sacrifice (vs 100% SPY)",
            "",
            "| Portfolio | MaxDD | DD reduction | CAGR sacrifice | CAGR cost per 1pp DD |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for t in study["tradeoff"]:
        lines.append(
            f"| {labels.get(t['name'], t['name'])} | {pct(t['max_drawdown'])} | "
            f"{pct(t['dd_reduction_vs_spy'])} | {pct(t['cagr_sacrifice_vs_spy'])} | "
            f"{pct(t['cagr_cost_per_1pp_dd'])} |"
        )

    lines.extend(
        [
            "",
            "## Look-through exposures (monthly blend)",
            "",
            "| Portfolio | Equity | Bond | Gold | Cash | LT SPY | LT QQQ | LT SPY+QQQ |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for s in study["monthly"]:
        lt = s["look_through"]
        lines.append(
            f"| {labels[s['name']]} | {pct(lt['avg_equity'])} | {pct(lt['avg_bond'])} | "
            f"{pct(lt['avg_gold'])} | {pct(lt['avg_cash'])} | {pct(lt['avg_lookthrough_SPY'])} | "
            f"{pct(lt['avg_lookthrough_QQQ'])} | {pct(lt['avg_lookthrough_US_equity_overlap'])} |"
        )
    lines.append(
        "- Overlap note: outer SPY plus D+C internal SPY/QQQ creates **stacked US equity** look-through; "
        "80/20 is not '80% equity / 20% diversifiers'."
    )

    lines.extend(
        [
            "",
            "## Stress windows (total return)",
            "",
            "| Portfolio | 2000–02 | GFC 2008 | COVID 2020 | 2022 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for s in rows:
        st = s["stress"]
        lines.append(
            f"| {labels.get(s['name'], s['name'])} | "
            f"{pct(st.get('dotcom_2000_2002')) if st.get('dotcom_2000_2002') is not None else 'n/a (pre-sample)'} | "
            f"{pct(st.get('gfc_2008'))} | {pct(st.get('covid_2020'))} | {pct(st.get('bear_2022'))} |"
        )

    # Yearly table — SPY, DC, 80/20, 60/40
    focus = ["100_spy", "100_dc", "80_20", "60_40"]
    years = sorted({y for s in study["monthly"] if s["name"] in focus for y in s["yearly_returns"]})
    lines.extend(["", "## Calendar year returns", "", "| Year | " + " | ".join(labels[n] for n in focus) + " |", "|---|---:|---:|---:|---:|"])
    by_name = {s["name"]: s["yearly_returns"] for s in study["monthly"]}
    for y in years:
        lines.append(
            "| {y} | {vals} |".format(
                y=y,
                vals=" | ".join(pct(by_name[n].get(y)) for n in focus),
            )
        )

    lines.extend(
        [
            "",
            "## Cost sensitivity (monthly rebalance)",
            "",
            "| bps | Portfolio | CAGR | Sharpe | MaxDD | Ann. turnover |",
            "|---:|---|---:|---:|---:|---:|",
        ]
    )
    for row in study["cost_sensitivity"]:
        lines.append(
            f"| {row['bps']:.0f} | {labels[row['name']]} | {pct(row['cagr'])} | "
            f"{num(row['sharpe'])} | {pct(row['max_drawdown'])} | {num(row['ann_turnover'])} |"
        )

    lines.extend(
        [
            "",
            "## Monthly vs annual rebalance turnover",
            "",
            "| Portfolio | Monthly ann. TO | Annual ann. TO |",
            "|---|---:|---:|",
        ]
    )
    for row in study["turnover_month_vs_year"]:
        lines.append(
            f"| {labels[row['name']]} | {num(row['month_ann_turnover'])} | {num(row['year_ann_turnover'])} |"
        )

    lines.extend(
        [
            "",
            "## Annual rebalance — key metrics (robustness)",
            "",
            "| Portfolio | CAGR | Sharpe | MaxDD | Calmar |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for s in study["annual"]:
        st = s["stats"]
        lines.append(
            f"| {labels[s['name']]} | {pct(st['cagr'])} | {num(st['sharpe'])} | "
            f"{pct(st['max_drawdown'])} | {num(st['calmar'])} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation rules applied",
            "",
            "- Did **not** pick weights by highest Sharpe.",
            "- Asked whether 20% or 40% D+C can cut MaxDD without 100% D+C's ~210m relative underwater.",
            "- If blends still chronically lag SPY on relative NAV, reject for small-capital growth mandate.",
            "",
        ]
    )

    path = directory / "dc_sleeve_evaluation.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Artifacts
    summary_rows = []
    for s in study["monthly"] + [study["bench_60_40"]]:
        summary_rows.append(
            {
                "name": s["name"],
                **{f"stat_{k}": v for k, v in s["stats"].items()},
                **{f"rel_{k}": v for k, v in s["relative_vs_spy"].items() if not isinstance(v, dict)},
                **{f"lt_{k}": v for k, v in s["look_through"].items() if not isinstance(v, dict)},
                "end_value_10k": s["end_value_10k"],
                "ann_turnover": s.get("ann_turnover"),
            }
        )
    pd.DataFrame(summary_rows).to_csv(directory / "sleeve_summary.csv", index=False)
    pd.DataFrame(study["tradeoff"]).to_csv(directory / "sleeve_tradeoff.csv", index=False)
    pd.DataFrame(study["cost_sensitivity"]).to_csv(directory / "sleeve_cost_sensitivity.csv", index=False)
    serializable = {k: v for k, v in study.items()}
    # strip equity frames
    for block in ("monthly", "annual"):
        for item in serializable[block]:
            item.pop("equity", None)
    serializable["bench_60_40"].pop("equity", None)
    (directory / "sleeve_evaluation.json").write_text(
        json.dumps(serializable, indent=2, default=str), encoding="utf-8"
    )

    if promote_to is not None:
        promote_to.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        (promote_to.parent / "dc_sleeve_evaluation.json").write_text(
            json.dumps(serializable, indent=2, default=str), encoding="utf-8"
        )
    return path
