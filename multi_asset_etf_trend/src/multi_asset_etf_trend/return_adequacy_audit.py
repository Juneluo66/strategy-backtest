"""Return-adequacy audit for frozen multi_asset_etf_trend (no rule changes).

Judges whether ensemble_risk_balanced earns meaningful risk premia / timing value,
or mostly harvests BIL carry with a low-vol shell.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .artifacts import new_run_directory
from .backtest import buy_and_hold, monthly_rebalance_fixed, run_weight_schedule
from .config import TrendConfig, load_config
from .data import fetch_prices, load_ohlc, reuse_sibling_caches, strict_common_index
from .metrics import METRIC_C_DEFINITION, metric_c_relative_stats
from .signals import build_monthly_targets

COMPARE = [
    "bil_buy_hold",
    "ensemble_risk_balanced",
    "ensemble_equal",
    "sixty_forty_spy_ief_monthly",
    "spy_buy_hold",
]

PERIODS = [
    ("2008-2012", "2008-01-01", "2012-12-31"),
    ("2013-2017", "2013-01-01", "2017-12-31"),
    ("2018-2022", "2018-01-01", "2022-12-31"),
    ("2023-latest", "2023-01-01", None),
]

GROUP_MAP = {
    "equity": ["SPY", "EFA", "EEM"],
    "bonds": ["IEF", "TLT"],
    "gold": ["GLD"],
    "commodities": ["DBC"],
    "real_estate": ["VNQ"],
}


def _years(idx: pd.DatetimeIndex) -> float:
    return max((idx.max() - idx.min()).days / 365.25, 1 / 12)


def _cagr(returns: pd.Series) -> float:
    r = returns.dropna()
    if r.empty:
        return float("nan")
    eq = (1 + r).cumprod()
    return float(eq.iloc[-1] ** (1 / _years(r.index)) - 1)


def _maxdd(returns: pd.Series) -> float:
    r = returns.dropna()
    if r.empty:
        return float("nan")
    eq = (1 + r).cumprod()
    return float((eq / eq.cummax() - 1).min())


def _vol(returns: pd.Series) -> float:
    r = returns.dropna()
    if len(r) < 2:
        return float("nan")
    return float(r.std(ddof=1) * np.sqrt(252))


def _sortino(returns: pd.Series) -> float:
    r = returns.dropna()
    down = r[r < 0]
    if len(down) < 2 or down.std(ddof=1) == 0:
        return float("nan")
    return float(r.mean() / down.std(ddof=1) * np.sqrt(252))


def _sharpe_excess_bil(returns: pd.Series, bil: pd.Series) -> float:
    """Formal Sharpe with contemporaneous BIL as risk-free: E[r-rf]/σ(r)."""
    aligned = pd.concat([returns.rename("r"), bil.rename("rf")], axis=1).dropna()
    if len(aligned) < 2 or aligned["r"].std(ddof=1) == 0:
        return float("nan")
    excess = aligned["r"] - aligned["rf"]
    return float(excess.mean() / aligned["r"].std(ddof=1) * np.sqrt(252))


def _final_wealth(returns: pd.Series) -> float:
    r = returns.dropna()
    if r.empty:
        return float("nan")
    return float((1 + r).cumprod().iloc[-1])


def _calmar(cagr: float, maxdd: float) -> float:
    if not np.isfinite(cagr) or not np.isfinite(maxdd) or maxdd == 0:
        return float("nan")
    return float(cagr / abs(maxdd))


def _align_panels(opens: pd.DataFrame, closes: pd.DataFrame, symbols: list[str]):
    idx = strict_common_index(closes[symbols])
    return opens.reindex(idx)[symbols], closes.reindex(idx)[symbols]


def _avg_group_weights(equity: pd.DataFrame, risk: list[str], cash: str) -> dict[str, float]:
    out: dict[str, float] = {}
    risk_sum = 0.0
    for g, members in GROUP_MAP.items():
        cols = [f"w_{s}" for s in members if f"w_{s}" in equity.columns]
        out[f"avg_w_{g}"] = float(equity[cols].sum(axis=1).mean()) if cols else float("nan")
        risk_sum += out[f"avg_w_{g}"] if np.isfinite(out[f"avg_w_{g}"]) else 0.0
    out["avg_w_bil"] = float(equity["w_bil"].mean()) if "w_bil" in equity.columns else float("nan")
    out["avg_w_risk"] = float(risk_sum)
    return out


def full_sample_row(
    name: str,
    equity: pd.DataFrame,
    bil_ret: pd.Series,
    *,
    risk: list[str],
    cash: str,
) -> dict:
    net = equity["net_return"].dropna()
    bil = bil_ret.reindex(net.index)
    cagr = _cagr(net)
    bil_cagr = _cagr(bil)
    maxdd = _maxdd(net)
    row = {
        "strategy": name,
        "cagr": cagr,
        "cagr_minus_bil": cagr - bil_cagr if np.isfinite(cagr) and np.isfinite(bil_cagr) else np.nan,
        "sharpe_rf_bil": _sharpe_excess_bil(net, bil),
        "sortino": _sortino(net),
        "max_drawdown": maxdd,
        "calmar": _calmar(cagr, maxdd),
        "final_wealth": _final_wealth(net),
        "volatility": _vol(net),
        "start": str(net.index.min().date()) if len(net) else None,
        "end": str(net.index.max().date()) if len(net) else None,
    }
    if name in {"ensemble_risk_balanced", "ensemble_equal"}:
        row.update(_avg_group_weights(equity.loc[net.index], risk, cash))
    else:
        row["avg_w_risk"] = 1.0 if name != "bil_buy_hold" else 0.0
        row["avg_w_bil"] = 1.0 if name == "bil_buy_hold" else 0.0
        for g in GROUP_MAP:
            row[f"avg_w_{g}"] = np.nan
        if name == "spy_buy_hold":
            row["avg_w_equity"] = 1.0
            row["avg_w_risk"] = 1.0
        if name == "sixty_forty_spy_ief_monthly":
            # drifted averages from weight cols if present
            if "w_SPY" in equity.columns:
                row["avg_w_equity"] = float(equity["w_SPY"].mean())
                row["avg_w_bonds"] = float(equity["w_IEF"].mean()) if "w_IEF" in equity.columns else np.nan
                row["avg_w_risk"] = float(
                    equity[[c for c in equity.columns if c.startswith("w_") and c != "w_bil"]]
                    .sum(axis=1)
                    .mean()
                )
                row["avg_w_bil"] = 0.0
    return row


def period_row(
    name: str,
    equity: pd.DataFrame,
    bil_ret: pd.Series,
    sixty_ret: pd.Series,
    start: str,
    end: Optional[str],
) -> dict:
    net = equity["net_return"]
    if end:
        sl = net.loc[start:end]
    else:
        sl = net.loc[start:]
    sl = sl.dropna()
    bil = bil_ret.reindex(sl.index).dropna()
    common = sl.index.intersection(bil.index)
    sl = sl.reindex(common)
    bil = bil.reindex(common)
    sixty = sixty_ret.reindex(common).dropna()
    cagr = _cagr(sl)
    bil_cagr = _cagr(bil)
    return {
        "strategy": name,
        "period_start": start,
        "period_end": end or str(sl.index.max().date()) if len(sl) else end,
        "strategy_cagr": cagr,
        "bil_cagr": bil_cagr,
        "cagr_minus_bil": cagr - bil_cagr if np.isfinite(cagr) and np.isfinite(bil_cagr) else np.nan,
        "sixty_forty_cagr": _cagr(sixty),
        "max_drawdown": _maxdd(sl),
        "sharpe_rf_bil": _sharpe_excess_bil(sl, bil),
        "avg_bil_weight": float(equity.reindex(common)["w_bil"].mean())
        if "w_bil" in equity.columns
        else (1.0 if name == "bil_buy_hold" else 0.0),
    }


def rolling_beat_rate(
    strategy: pd.Series,
    benchmark: pd.Series,
    window_years: int,
    step: int = 21,
) -> dict:
    aligned = pd.concat([strategy.rename("s"), benchmark.rename("b")], axis=1).dropna()
    span = int(252 * window_years)
    if len(aligned) < span:
        return {"window_years": window_years, "n": 0, "beat_rate": np.nan}
    beats = 0
    n = 0
    for i in range(0, len(aligned) - span + 1, step):
        w = aligned.iloc[i : i + span]
        cs = _cagr(w["s"])
        cb = _cagr(w["b"])
        if np.isfinite(cs) and np.isfinite(cb):
            n += 1
            if cs > cb:
                beats += 1
    return {
        "window_years": window_years,
        "n": n,
        "beat_rate": (beats / n) if n else np.nan,
        "beats": beats,
    }


def return_decomposition(
    erb: dict,
    ee: dict,
    equal_always_on: dict,
    bil_ret: pd.Series,
    closes: pd.DataFrame,
    risk: list[str],
    cash: str,
) -> dict:
    """
    Telescoping geometric + daily excess attribution.

    BIL interest earned while parked in cash is NOT labeled trend alpha.
    """
    erb_net = erb["equity"]["net_return"].dropna()
    erb_gross = erb["equity"]["gross_return"].reindex(erb_net.index).dropna()
    ee_net = ee["equity"]["net_return"].reindex(erb_net.index).dropna()
    passive_net = equal_always_on["equity"]["net_return"].reindex(erb_net.index).dropna()
    bil = bil_ret.reindex(erb_net.index).dropna()
    idx = erb_net.index.intersection(ee_net.index).intersection(passive_net.index).intersection(bil.index)

    c_bil = _cagr(bil.loc[idx])
    c_passive = _cagr(passive_net.loc[idx])
    c_ee = _cagr(ee_net.loc[idx])
    c_erb_gross = _cagr(erb_gross.loc[idx])
    c_erb = _cagr(erb_net.loc[idx])

    # Daily excess vs BIL attribution for erb: sum_i w_i (r_i - r_bil) - cost
    asset_rets = closes[risk + [cash]].pct_change(fill_method=None).reindex(idx)
    weights = erb["weights"].reindex(idx) if not erb["weights"].empty else pd.DataFrame(index=idx)
    daily_parts = {}
    residual = erb_net.loc[idx].copy()
    # Reconstruct approximate gross from weights * close-to-close (attribution basis)
    # Prefer equity gross/cost when available.
    cost = erb["equity"]["cost"].reindex(idx).fillna(0.0)
    attributed = pd.Series(0.0, index=idx)
    for sym in risk + [cash]:
        wcol = sym if sym in weights.columns else None
        if wcol is None:
            daily_parts[sym] = pd.Series(0.0, index=idx)
            continue
        # Use prior weight approx: weights in engine are end-of-day after drift.
        # Attribution uses same-day end weight × close-to-close as research approx;
        # labeled APPROXIMATE_END_WEIGHT.
        w = weights[sym].reindex(idx).fillna(0.0)
        r = asset_rets[sym].reindex(idx)
        part = w * r
        daily_parts[sym] = part
        attributed = attributed + part.fillna(0.0)

    # Scale note: overnight/intraday engine ≠ pure close-to-close; reconcile via residual.
    recon_gross = attributed
    recon_net = recon_gross - cost
    recon_err = (erb_net.loc[idx] - recon_net).dropna()

    group_ann = {}
    for g, members in GROUP_MAP.items():
        series = sum((daily_parts[m].fillna(0.0) for m in members if m in daily_parts), pd.Series(0.0, index=idx))
        group_ann[g] = float(series.mean() * 252) if len(series) else np.nan
    bil_ann = float(daily_parts[cash].fillna(0.0).mean() * 252) if cash in daily_parts else np.nan
    cost_ann = float(cost.mean() * 252) if len(cost) else np.nan
    # Excess over BIL from risk sleeves only (arithmetic ann.)
    risk_excess_ann = {}
    for sym in risk:
        if sym not in daily_parts:
            continue
        w = weights[sym].reindex(idx).fillna(0.0) if sym in weights.columns else 0.0
        excess = w * (asset_rets[sym] - bil)
        risk_excess_ann[sym] = float(excess.fillna(0.0).mean() * 252)

    return {
        "method": {
            "telescoping_cagr": (
                "bil → equal_weight_8_always_on → ensemble_equal → "
                "ensemble_risk_balanced_gross → net"
            ),
            "daily_attribution": "end_of_day_weight * close_to_close; APPROXIMATE vs open/close engine",
            "bil_interest_is_not_trend_alpha": True,
        },
        "telescoping_cagr": {
            "bil_base": c_bil,
            "passive_equal_weight_8": c_passive,
            "passive_risk_premium_vs_bil": c_passive - c_bil,
            "ensemble_equal": c_ee,
            "timing_vs_passive_equal": c_ee - c_passive,
            "ensemble_risk_balanced_gross": c_erb_gross,
            "risk_balance_vs_ensemble_equal": c_erb_gross - c_ee,
            "ensemble_risk_balanced_net": c_erb,
            "cost_drag": c_erb_gross - c_erb,
            "total_check_net_minus_bil": c_erb - c_bil,
        },
        "arithmetic_ann_contribution_approx": {
            "bil_weight_times_bil_return": bil_ann,
            "group_weight_times_asset_return": group_ann,
            "cost_drag": -cost_ann,
            "risk_asset_excess_over_bil": risk_excess_ann,
            "sum_risk_excess_over_bil": float(sum(risk_excess_ann.values())) if risk_excess_ann else np.nan,
            "reconciliation_mean_daily_error": float(recon_err.mean()) if len(recon_err) else np.nan,
            "reconciliation_ann_error_approx": float(recon_err.mean() * 252) if len(recon_err) else np.nan,
        },
        "interpretation": [
            "BIL基础收益 = telescoping bil_base (and bil_weight_times_bil_return).",
            "各风险ETF被动收益贡献 ≈ passive_equal_weight_8 − bil_base (满仓等权溢价).",
            "趋势择时贡献 = ensemble_equal − passive_equal_weight_8 (通常为负的CAGR、换取回撤).",
            "风险平衡贡献 = erb_gross − ensemble_equal.",
            "交易成本拖累 = erb_gross − erb_net.",
            "持有BIL的利息不是趋势alpha；alpha仅存在于相对BIL/被动的增量项。",
        ],
    }


def evaluate_adequacy(
    full: pd.DataFrame,
    periods: pd.DataFrame,
    rolling: dict,
    decomp: dict,
    mc_bil: dict,
) -> dict:
    """
    A CAPITAL_PRESERVATION_CANDIDATE | B MULTI_ASSET_RETURN_CANDIDATE | C REJECTED
    """
    erb = full.set_index("strategy").loc["ensemble_risk_balanced"]
    bil = full.set_index("strategy").loc["bil_buy_hold"]
    sf = full.set_index("strategy").loc["sixty_forty_spy_ief_monthly"]

    excess = float(erb["cagr_minus_bil"])
    wealth_vs_bil = float(erb["final_wealth"] / bil["final_wealth"])
    wealth_vs_sf = float(erb["final_wealth"] / sf["final_wealth"])
    timing = float(decomp["telescoping_cagr"]["timing_vs_passive_equal"])
    risk_bal = float(decomp["telescoping_cagr"]["risk_balance_vs_ensemble_equal"])
    passive_prem = float(decomp["telescoping_cagr"]["passive_risk_premium_vs_bil"])
    beat_bil_3 = float(rolling["vs_bil_3y"]["beat_rate"])
    beat_bil_5 = float(rolling["vs_bil_5y"]["beat_rate"])
    beat_sf_3 = float(rolling["vs_60_40_3y"]["beat_rate"])
    beat_sf_5 = float(rolling["vs_60_40_5y"]["beat_rate"])

    # Period: how often erb CAGR within 2pp of 60/40 or higher
    erb_p = periods[periods.strategy == "ensemble_risk_balanced"]
    competitive_periods = 0
    for _, row in erb_p.iterrows():
        if np.isfinite(row["strategy_cagr"]) and np.isfinite(row["sixty_forty_cagr"]):
            if row["strategy_cagr"] + 0.02 >= row["sixty_forty_cagr"]:
                competitive_periods += 1
    n_periods = int(len(erb_p))

    checks = {
        "beats_bil_cagr_1pp": excess >= 0.01,
        "wealth_vs_bil_gt_1_2": wealth_vs_bil >= 1.2,
        "metric_c_bil_final_gt_1": float(mc_bil["final_relative_nav"]) > 1.0,
        "rolling_beat_bil_3y_ge_60": beat_bil_3 >= 0.60,
        "rolling_beat_bil_5y_ge_60": beat_bil_5 >= 0.60,
        "maxdd_much_better_than_60_40": float(erb["max_drawdown"]) > float(sf["max_drawdown"]) + 0.10,
        "lags_60_40_wealth": wealth_vs_sf < 0.85,
        "rolling_beat_60_40_3y_lt_40": beat_sf_3 < 0.40,
        "rolling_beat_60_40_5y_lt_40": beat_sf_5 < 0.40,
        "incremental_vs_bil_not_tiny": excess >= 0.015
        or (passive_prem + timing + risk_bal) >= 0.015,
        "not_only_bil_carry": float(erb.get("avg_w_bil", 0.5)) < 0.75 and excess >= 0.01,
    }

    # B: return-competitive vs both BIL and 60/40
    is_b = bool(
        checks["beats_bil_cagr_1pp"]
        and checks["rolling_beat_bil_3y_ge_60"]
        and (beat_sf_3 >= 0.45 or beat_sf_5 >= 0.45 or competitive_periods >= max(2, n_periods // 2))
        and wealth_vs_sf >= 0.90
    )
    # C: incremental return too weak
    is_c = bool(
        (not checks["incremental_vs_bil_not_tiny"])
        or (not checks["not_only_bil_carry"])
        or excess < 0.01
        or wealth_vs_bil < 1.1
    )
    # A: preserves capital vs BIL, stable low DD, but clearly behind 60/40
    is_a = bool(
        checks["beats_bil_cagr_1pp"]
        and checks["metric_c_bil_final_gt_1"]
        and checks["maxdd_much_better_than_60_40"]
        and checks["lags_60_40_wealth"]
        and checks["rolling_beat_60_40_3y_lt_40"]
        and checks["not_only_bil_carry"]
        and not is_b
        and not is_c
    )

    if is_b:
        label = "MULTI_ASSET_RETURN_CANDIDATE"
    elif is_a:
        label = "CAPITAL_PRESERVATION_CANDIDATE"
    elif is_c:
        label = "REJECTED"
    else:
        # Fallback: preservation-leaning if beats BIL + low DD else reject
        if checks["beats_bil_cagr_1pp"] and checks["maxdd_much_better_than_60_40"] and checks["lags_60_40_wealth"]:
            label = "CAPITAL_PRESERVATION_CANDIDATE"
        else:
            label = "REJECTED"

    return {
        "label": label,
        "checks": checks,
        "diagnostics": {
            "excess_cagr_vs_bil": excess,
            "wealth_vs_bil": wealth_vs_bil,
            "wealth_vs_60_40": wealth_vs_sf,
            "timing_cagr_vs_passive": timing,
            "risk_balance_cagr": risk_bal,
            "passive_premium_cagr": passive_prem,
            "beat_bil_3y": beat_bil_3,
            "beat_bil_5y": beat_bil_5,
            "beat_60_40_3y": beat_sf_3,
            "beat_60_40_5y": beat_sf_5,
            "periods_near_60_40": competitive_periods,
            "n_periods": n_periods,
            "avg_bil_weight": float(erb.get("avg_w_bil", np.nan)),
            "cagr_per_pp_maxdd_vs_bil": (
                (
                    excess
                    / (
                        (abs(float(erb["max_drawdown"])) - abs(float(bil["max_drawdown"])))
                        * 100.0
                    )
                )
                if np.isfinite(excess)
                and (abs(float(erb["max_drawdown"])) - abs(float(bil["max_drawdown"]))) > 1e-9
                else np.nan
            ),
        },
        "notes": [
            "No IBKR / frozen-rule changes.",
            "BIL carry is not trend alpha.",
            "Label is research-only, not a live profitability claim.",
        ],
    }


def _fmt_pct(x, d=2):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "n/a"
    return f"{100 * float(x):.{d}f}%"


def _fmt_num(x, d=3):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "n/a"
    return f"{float(x):.{d}f}"


def render_report(
    config: TrendConfig,
    full: pd.DataFrame,
    periods: pd.DataFrame,
    extras: dict,
    decomp: dict,
    verdict: dict,
    run_dir: Path,
) -> str:
    lines: list[str] = []
    lines.append("# Multi-Asset ETF Trend — Return Adequacy Audit")
    lines.append("")
    lines.append(f"**Verdict:** `{verdict['label']}`")
    lines.append("")
    lines.append(
        "Frozen rules unchanged (universe, 3/6/12 signals, 63d vol, weights, monthly cadence, "
        "5bp next-open). This audit only asks whether `ensemble_risk_balanced` earns enough "
        "*incremental* return beyond long BIL, or is mainly a cash sleeve with a Sharpe coat of paint."
    )
    lines.append("")
    lines.append("Inflation / real purchasing power: **NOT_COMPUTED** (no reliable PIT inflation series in this track; will not backfill with latest CPI).")
    lines.append("")
    lines.append("## 1. Full sample")
    lines.append("")
    cols = [
        "strategy",
        "cagr",
        "cagr_minus_bil",
        "sharpe_rf_bil",
        "sortino",
        "max_drawdown",
        "calmar",
        "final_wealth",
        "avg_w_risk",
        "avg_w_equity",
        "avg_w_bonds",
        "avg_w_gold",
        "avg_w_commodities",
        "avg_w_real_estate",
        "avg_w_bil",
    ]
    headers = [
        "Strategy",
        "CAGR",
        "vs BIL",
        "Sharpe(rf=BIL)",
        "Sortino",
        "MaxDD",
        "Calmar",
        "Final W",
        "Avg risk",
        "Eq",
        "Bond",
        "Gold",
        "Cmdty",
        "RE",
        "BIL",
    ]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for name in COMPARE:
        m = full.set_index("strategy").loc[name]
        row = []
        for c in cols:
            if c == "strategy":
                row.append(name)
                continue
            v = m.get(c)
            if c in {"final_wealth", "sharpe_rf_bil", "sortino", "calmar"}:
                row.append(_fmt_num(v))
            else:
                row.append(_fmt_pct(v))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append(f"Sample: `{full.iloc[0]['start']}` → `{full.iloc[0]['end']}`")
    lines.append("")
    lines.append("## 2. Periods")
    lines.append("")
    lines.append("| Period | Strategy | Strat CAGR | BIL CAGR | Strat−BIL | 60/40 CAGR | MaxDD | Sharpe(rf=BIL) | Avg BIL |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in periods.iterrows():
        if r["strategy"] not in {
            "ensemble_risk_balanced",
            "ensemble_equal",
            "sixty_forty_spy_ief_monthly",
            "bil_buy_hold",
            "spy_buy_hold",
        }:
            continue
        label = r.get("period_label", r["period_start"])
        lines.append(
            f"| {label} | {r['strategy']} | {_fmt_pct(r['strategy_cagr'])} | "
            f"{_fmt_pct(r['bil_cagr'])} | {_fmt_pct(r['cagr_minus_bil'])} | {_fmt_pct(r['sixty_forty_cagr'])} | "
            f"{_fmt_pct(r['max_drawdown'])} | {_fmt_num(r['sharpe_rf_bil'])} | {_fmt_pct(r['avg_bil_weight'])} |"
        )
    lines.append("")
    lines.append("## 3. Relative sufficiency")
    lines.append("")
    lines.append(f"- Strategy final wealth / BIL final wealth: **{_fmt_num(extras['wealth_vs_bil'])}**")
    lines.append(f"- Metric C vs BIL final relative NAV: **{_fmt_num(extras['mc_bil']['final_relative_nav'])}**")
    lines.append(
        f"- Metric C vs BIL max relative UW: {_fmt_pct(extras['mc_bil']['relative_max_dd'])}; "
        f"still underwater: {extras['mc_bil']['currently_underwater']}"
    )
    lines.append(f"- Definition: `{METRIC_C_DEFINITION}`")
    lines.append(
        f"- Rolling 3y beat BIL: {_fmt_pct(extras['rolling']['vs_bil_3y']['beat_rate'])} "
        f"(n={extras['rolling']['vs_bil_3y']['n']})"
    )
    lines.append(
        f"- Rolling 5y beat BIL: {_fmt_pct(extras['rolling']['vs_bil_5y']['beat_rate'])} "
        f"(n={extras['rolling']['vs_bil_5y']['n']})"
    )
    lines.append(
        f"- Rolling 3y beat 60/40: {_fmt_pct(extras['rolling']['vs_60_40_3y']['beat_rate'])} "
        f"(n={extras['rolling']['vs_60_40_3y']['n']})"
    )
    lines.append(
        f"- Rolling 5y beat 60/40: {_fmt_pct(extras['rolling']['vs_60_40_5y']['beat_rate'])} "
        f"(n={extras['rolling']['vs_60_40_5y']['n']})"
    )
    lines.append(
        f"- Annualized excess over BIL (geometric CAGR gap): {_fmt_pct(extras['excess_cagr'])}"
    )
    lines.append(
        f"- CAGR per +1pp MaxDD vs BIL (excess / ΔMaxDD × 1pp): "
        f"{_fmt_pct(verdict['diagnostics']['cagr_per_pp_maxdd_vs_bil'], 3)}"
    )
    lines.append("- Real purchasing power vs inflation: **NOT_COMPUTED**")
    lines.append("")
    lines.append("## 4. Return sources (not labeling BIL interest as trend alpha)")
    lines.append("")
    tc = decomp["telescoping_cagr"]
    lines.append("| Component | CAGR |")
    lines.append("|---|---:|")
    lines.append(f"| BIL base | {_fmt_pct(tc['bil_base'])} |")
    lines.append(f"| Passive EW8 (always on) | {_fmt_pct(tc['passive_equal_weight_8'])} |")
    lines.append(f"| Passive risk premium vs BIL | {_fmt_pct(tc['passive_risk_premium_vs_bil'])} |")
    lines.append(f"| Timing vs passive EW8 (`ensemble_equal − EW8`) | {_fmt_pct(tc['timing_vs_passive_equal'])} |")
    lines.append(f"| Risk-balance vs `ensemble_equal` (gross) | {_fmt_pct(tc['risk_balance_vs_ensemble_equal'])} |")
    lines.append(f"| Cost drag | {_fmt_pct(tc['cost_drag'])} |")
    lines.append(f"| Net `ensemble_risk_balanced` | {_fmt_pct(tc['ensemble_risk_balanced_net'])} |")
    lines.append(f"| Check: net − BIL | {_fmt_pct(tc['total_check_net_minus_bil'])} |")
    lines.append("")
    lines.append("Arithmetic annualized group contributions (end-weight × close-to-close approx):")
    lines.append("")
    lines.append("| Piece | Ann. contrib |")
    lines.append("|---|---:|")
    aa = decomp["arithmetic_ann_contribution_approx"]
    lines.append(f"| BIL weight × BIL return | {_fmt_pct(aa['bil_weight_times_bil_return'])} |")
    for g, v in aa["group_weight_times_asset_return"].items():
        lines.append(f"| {g} weight × asset return | {_fmt_pct(v)} |")
    lines.append(f"| Cost drag | {_fmt_pct(aa['cost_drag'])} |")
    lines.append(f"| Sum risk excess over BIL | {_fmt_pct(aa['sum_risk_excess_over_bil'])} |")
    lines.append(f"| Reconciliation ann. error (engine vs CC approx) | {_fmt_pct(aa['reconciliation_ann_error_approx'])} |")
    lines.append("")
    for note in decomp["interpretation"]:
        lines.append(f"- {note}")
    lines.append("")
    lines.append("## Gate checklist")
    lines.append("")
    for k, v in verdict["checks"].items():
        lines.append(f"- [{'x' if v else ' '}] `{k}`")
    lines.append("")
    lines.append("## Decision")
    lines.append("")
    if verdict["label"] == "CAPITAL_PRESERVATION_CANDIDATE":
        lines.append(
            "**A. CAPITAL_PRESERVATION_CANDIDATE** — Beats BIL with shallow drawdowns and stable "
            "risk-adjusted stats, but long-run wealth and rolling windows remain clearly behind 60/40. "
            "Useful as a preservation / ballast research sleeve, not as a return engine."
        )
    elif verdict["label"] == "MULTI_ASSET_RETURN_CANDIDATE":
        lines.append(
            "**B. MULTI_ASSET_RETURN_CANDIDATE** — Incremental return vs BIL and competitiveness vs "
            "60/40 are both adequate on rolling/period evidence."
        )
    else:
        lines.append(
            "**C. REJECTED** — After removing BIL base yield, risk-asset/timing incremental return is "
            "too thin to justify the complexity."
        )
    lines.append("")
    lines.append("No IBKR changes. No frozen-rule edits. No further parameter search.")
    lines.append("")
    lines.append("## Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append(f"cd {config.project_root}")
    lines.append("python3 -m pip install -e '.[dev]'")
    lines.append("multi-asset-etf-trend return-adequacy-audit")
    lines.append("pytest -q")
    lines.append("```")
    lines.append("")
    lines.append(f"Run directory: `{run_dir}`")
    lines.append("")
    return "\n".join(lines)


def run_return_adequacy_audit(config: Optional[TrendConfig] = None) -> dict:
    config = config or load_config()
    reuse_sibling_caches(config)
    fetch_prices(config, refresh=False)

    opens_all, closes_all, _ = load_ohlc(config)
    opens, closes = _align_panels(opens_all, closes_all, config.all_symbols)
    risk = config.risk_symbols
    cash = config.cash_symbol

    bil_bh = buy_and_hold(opens, closes, cash)
    spy_bh = buy_and_hold(opens, closes, "SPY")
    sixty = monthly_rebalance_fixed(
        opens, closes, {"SPY": 0.6, "IEF": 0.4}, one_way_bps=config.one_way_bps
    )
    equal_always = monthly_rebalance_fixed(
        opens, closes, {s: 1.0 / len(risk) for s in risk}, one_way_bps=config.one_way_bps
    )

    runs: dict[str, dict] = {
        "bil_buy_hold": {"equity": bil_bh, "trades": pd.DataFrame(), "weights": pd.DataFrame()},
        "spy_buy_hold": {"equity": spy_bh, "trades": pd.DataFrame(), "weights": pd.DataFrame()},
        "sixty_forty_spy_ief_monthly": sixty,
        "equal_weight_8_always_on": equal_always,
    }
    for version in ("ensemble_equal", "ensemble_risk_balanced"):
        targets = build_monthly_targets(
            closes, risk, cash, version, vol_lookback=config.vol_lookback_days
        )
        runs[version] = run_weight_schedule(
            opens, closes, targets, one_way_bps=config.one_way_bps, symbols=risk + [cash]
        )

    # Common start = max of first equity dates among compare set
    start_dates = [runs[n]["equity"].index.min() for n in COMPARE if not runs[n]["equity"].empty]
    common_start = max(start_dates)
    for name, run in runs.items():
        eq = run["equity"]
        run["equity"] = eq.loc[eq.index >= common_start]
        if "weights" in run and not run["weights"].empty:
            run["weights"] = run["weights"].loc[run["weights"].index >= common_start]

    bil_ret = closes[cash].pct_change(fill_method=None)
    sixty_ret = runs["sixty_forty_spy_ief_monthly"]["equity"]["net_return"]

    full_rows = [
        full_sample_row(name, runs[name]["equity"], bil_ret, risk=risk, cash=cash) for name in COMPARE
    ]
    full_df = pd.DataFrame(full_rows)

    period_rows = []
    for label, start, end in PERIODS:
        # clip start to common_start
        s0 = max(pd.Timestamp(start), common_start)
        for name in COMPARE:
            period_rows.append(
                {
                    **period_row(
                        name,
                        runs[name]["equity"],
                        bil_ret,
                        sixty_ret,
                        str(s0.date()),
                        end,
                    ),
                    "period_label": label,
                }
            )
    periods_df = pd.DataFrame(period_rows)

    erb_net = runs["ensemble_risk_balanced"]["equity"]["net_return"]
    rolling = {
        "vs_bil_3y": rolling_beat_rate(erb_net, bil_ret, 3),
        "vs_bil_5y": rolling_beat_rate(erb_net, bil_ret, 5),
        "vs_60_40_3y": rolling_beat_rate(erb_net, sixty_ret, 3),
        "vs_60_40_5y": rolling_beat_rate(erb_net, sixty_ret, 5),
    }
    mc_bil = metric_c_relative_stats(erb_net, bil_ret)
    # drop frame for json
    mc_bil_json = {k: v for k, v in mc_bil.items() if k != "frame"}

    decomp = return_decomposition(
        runs["ensemble_risk_balanced"],
        runs["ensemble_equal"],
        runs["equal_weight_8_always_on"],
        bil_ret,
        closes,
        risk,
        cash,
    )

    bil_wealth = float(full_df.set_index("strategy").loc["bil_buy_hold", "final_wealth"])
    erb_wealth = float(full_df.set_index("strategy").loc["ensemble_risk_balanced", "final_wealth"])
    extras = {
        "wealth_vs_bil": erb_wealth / bil_wealth if bil_wealth else np.nan,
        "mc_bil": mc_bil_json,
        "rolling": rolling,
        "excess_cagr": float(
            full_df.set_index("strategy").loc["ensemble_risk_balanced", "cagr_minus_bil"]
        ),
        "inflation": {"status": "NOT_COMPUTED", "reason": "no_reliable_PIT_inflation_series"},
    }

    verdict = evaluate_adequacy(full_df, periods_df, rolling, decomp, mc_bil_json)

    run_dir = new_run_directory(config, "return-adequacy-audit")
    full_df.to_csv(run_dir / "return_adequacy_full.csv", index=False)
    periods_df.to_csv(run_dir / "return_adequacy_periods.csv", index=False)
    pd.DataFrame(
        [
            {"benchmark": "BIL", **rolling["vs_bil_3y"]},
            {"benchmark": "BIL", **rolling["vs_bil_5y"]},
            {"benchmark": "60_40", **rolling["vs_60_40_3y"]},
            {"benchmark": "60_40", **rolling["vs_60_40_5y"]},
        ]
    ).to_csv(run_dir / "return_adequacy_rolling.csv", index=False)
    (run_dir / "return_adequacy_decomposition.json").write_text(
        json.dumps(decomp, indent=2, default=float), encoding="utf-8"
    )
    (run_dir / "return_adequacy_verdict.json").write_text(
        json.dumps(verdict, indent=2, default=float), encoding="utf-8"
    )
    (run_dir / "return_adequacy_extras.json").write_text(
        json.dumps(extras, indent=2, default=float), encoding="utf-8"
    )

    report = render_report(config, full_df, periods_df, extras, decomp, verdict, run_dir)
    (run_dir / "multi_asset_etf_trend_return_adequacy.md").write_text(report, encoding="utf-8")
    for fname in (
        "multi_asset_etf_trend_return_adequacy.md",
        "return_adequacy_full.csv",
        "return_adequacy_periods.csv",
        "return_adequacy_rolling.csv",
    ):
        src = run_dir / fname if fname != "multi_asset_etf_trend_return_adequacy.md" else run_dir / fname
        # publish primary markdown + csv aliases
        if fname.endswith(".md"):
            shutil.copy2(run_dir / fname, config.reports_dir / fname)
        else:
            shutil.copy2(run_dir / fname, config.reports_dir / fname)
    shutil.copy2(
        run_dir / "return_adequacy_decomposition.json",
        config.reports_dir / "return_adequacy_decomposition.json",
    )
    shutil.copy2(
        run_dir / "return_adequacy_verdict.json",
        config.reports_dir / "return_adequacy_verdict.json",
    )

    return {
        "run_dir": str(run_dir),
        "verdict": verdict,
        "common_start": str(common_start.date()),
        "full": full_df,
    }
