"""Orchestrate Phases 1–7 for low_max_defensive research."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from typing import Optional

import numpy as np
import pandas as pd

from .anatomy import anatomy_summary, anatomy_table
from .config import FrozenConfig, load_config
from .crisis import crisis_metrics, detect_spy_stress_windows
from .data_access import buy_and_hold_results, empty_trades, ensure_style_etf, load_panels
from .metrics_ext import portfolio_report
from .portfolio_bt import run_portfolio
from .report import write_reports
from .residual import residual_exclusion_experiment


def _run_named(config: FrozenConfig, opens, closes, volumes, provider, mode: str, exclude_frac: float = 0.0):
    return run_portfolio(
        opens,
        closes,
        volumes,
        mode=mode,
        lookback=config.lookback,
        top_returns=config.top_returns,
        min_dollar_volume=config.min_dollar_volume,
        one_way_bps=config.one_way_bps,
        membership_on=provider.symbols_on,
        exclude_frac=exclude_frac,
        portfolio_decile=config.portfolio_decile,
        max_portfolio_size=config.max_portfolio_size,
    )


def run_research(config: Optional[FrozenConfig] = None) -> Path:
    config = config or load_config()
    opens, closes, volumes, _vix, spy, provider = load_panels(config)
    spy_rets = spy.pct_change(fill_method=None)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.reports_dir / "runs" / f"{stamp}_low_max_defensive"
    run_dir.mkdir(parents=True, exist_ok=True)

    # --- Core portfolios (frozen MAX definition) ---
    ew_res, ew_h, ew_t, _ = _run_named(config, opens, closes, volumes, provider, "ew")
    low_res, low_h, low_t, _ = _run_named(config, opens, closes, volumes, provider, "low_max")
    excl = {}
    for frac in config.raw["exclusion_fractions"]:
        res, h, t, _ = _run_named(config, opens, closes, volumes, provider, "exclude_high", frac)
        excl[frac] = {"results": res, "holdings": h, "trades": t}

    primary_frac = float(config.raw["primary_exclusion"])
    ex20 = excl[primary_frac]

    # Align common evaluation window: first date where all active portfolios have exposure
    start = max(
        ew_res.loc[ew_res["exposure"] > 0].index.min(),
        low_res.loc[low_res["exposure"] > 0].index.min(),
        ex20["results"].loc[ex20["results"]["exposure"] > 0].index.min(),
    )
    end = min(ew_res.index.max(), low_res.index.max(), spy.index.max())

    spy_bh = buy_and_hold_results(spy.loc[start:end], "SPY_BH")

    # PHASE 1 — benchmarks
    bench_rows = []
    for label, results, trades in [
        ("SPY_BH", spy_bh, empty_trades()),
        ("EW_HIST_SP500", ew_res.loc[start:end], ew_t),
        ("LOW_MAX", low_res.loc[start:end], low_t),
    ]:
        bench_rows.append(portfolio_report(results, trades, spy_rets, label, str(start.date()), str(end.date())))

    style_notes = []
    for symbol, role in config.raw["style_etfs"].items():
        series = ensure_style_etf(config.cache_dir, symbol)
        if series is None or series.dropna().empty:
            style_notes.append(f"{symbol} ({role}): UNAVAILABLE")
            continue
        etf_start = max(start, series.dropna().index.min())
        if etf_start >= end:
            style_notes.append(f"{symbol} ({role}): no overlap with research window")
            continue
        bh = buy_and_hold_results(series.loc[etf_start:end], symbol)
        row = portfolio_report(bh, empty_trades(), spy_rets, f"{symbol}_{role}", str(etf_start.date()), str(end.date()))
        row["note"] = f"comparable only from {etf_start.date()} (ETF inception / first free bar); not backfilled"
        bench_rows.append(row)
        style_notes.append(f"{symbol} ({role}): compared from {etf_start.date()} to {end.date()}")

    benchmarks = pd.DataFrame(bench_rows)

    # Value delivered checklist vs SPY
    low_row = benchmarks.loc[benchmarks["label"] == "LOW_MAX"].iloc[0]
    spy_row = benchmarks.loc[benchmarks["label"] == "SPY_BH"].iloc[0]
    value_map = {
        "A_higher_return": bool(low_row["net_cagr"] > spy_row["net_cagr"]),
        "B_higher_sharpe": bool(low_row["net_sharpe"] > spy_row["net_sharpe"]),
        "C_lower_drawdown": bool(low_row["max_drawdown"] > spy_row["max_drawdown"]),
        "D_lower_beta": bool(low_row["beta_spy"] < 0.85),
        "E_better_downside_protection": bool(
            np.isfinite(low_row["downside_capture"]) and low_row["downside_capture"] < 0.95
        ),
    }
    value_map["F_nothing"] = not any(
        [
            value_map["A_higher_return"],
            value_map["B_higher_sharpe"],
            value_map["C_lower_drawdown"],
            value_map["D_lower_beta"],
            value_map["E_better_downside_protection"],
        ]
    )

    # PHASE 2 — exclusion grid
    excl_rows = []
    base = portfolio_report(ew_res.loc[start:end], ew_t, spy_rets, "EW_baseline", str(start.date()), str(end.date()))
    excl_rows.append(base)
    for frac, payload in excl.items():
        row = portfolio_report(
            payload["results"].loc[start:end],
            payload["trades"],
            spy_rets,
            f"EXCLUDE_HIGH_MAX_{int(frac*100)}",
            str(start.date()),
            str(end.date()),
        )
        row["delta_cagr"] = row["net_cagr"] - base["net_cagr"]
        row["delta_sharpe"] = row["net_sharpe"] - base["net_sharpe"]
        row["delta_max_dd"] = row["max_drawdown"] - base["max_drawdown"]
        row["delta_vol"] = row["volatility"] - base["volatility"]
        row["delta_turnover"] = row["annualized_turnover"] - base["annualized_turnover"]
        excl_rows.append(row)
    exclusion_grid = pd.DataFrame(excl_rows)

    # Monotonicity / sensitivity
    sharpes = [exclusion_grid.loc[exclusion_grid["label"] == f"EXCLUDE_HIGH_MAX_{int(f*100)}", "net_sharpe"].iloc[0] for f in config.raw["exclusion_fractions"]]
    base_s = base["net_sharpe"]
    improvements = [s - base_s for s in sharpes]
    if all(x > 0.02 for x in improvements) and sharpes == sorted(sharpes):
        exclusion_flag = "MONOTONIC_IMPROVEMENT"
    elif sum(x > 0.02 for x in improvements) == 1:
        exclusion_flag = "PARAMETER_SENSITIVE"
    elif sum(x > 0 for x in improvements) >= 2:
        exclusion_flag = "PARTIAL_IMPROVEMENT_NONMONOTONIC"
    else:
        exclusion_flag = "NO_SYSTEMATIC_IMPROVEMENT"

    # PHASE 3 — anatomy
    monthly_anatomy = anatomy_table(
        closes, low_h, provider.symbols_on, config.lookback, config.top_returns
    )
    anatomy = anatomy_summary(monthly_anatomy)

    # PHASE 4 — residual
    residual_vol = residual_exclusion_experiment(
        opens,
        closes,
        volumes,
        provider.symbols_on,
        lookback=config.lookback,
        top_returns=config.top_returns,
        min_dollar_volume=config.min_dollar_volume,
        one_way_bps=config.one_way_bps,
        exclude_frac=primary_frac,
        control="vol",
    )
    residual_beta = residual_exclusion_experiment(
        opens,
        closes,
        volumes,
        provider.symbols_on,
        lookback=config.lookback,
        top_returns=config.top_returns,
        min_dollar_volume=config.min_dollar_volume,
        one_way_bps=config.one_way_bps,
        exclude_frac=primary_frac,
        control="beta",
    )
    residual = pd.concat([residual_vol, residual_beta], ignore_index=True)
    vol_inc = residual_vol.loc[residual_vol["variant"] == "incremental_exclude_minus_all"].iloc[0]
    if vol_inc["net_sharpe"] <= 0.02:
        residual_flag = "MAX_IS_VOLATILITY_PROXY"
    elif vol_inc["net_sharpe"] > 0.05:
        residual_flag = "INCREMENTAL_AFTER_VOL_CONTROL"
    else:
        residual_flag = "NO_CLEAR_INCREMENT_AFTER_VOL_CONTROL"

    # PHASE 5 — regimes
    regime_rows = []
    for name, (rs, re) in config.raw["regimes"].items():
        for label, results, trades in [
            ("EW_baseline", ew_res, ew_t),
            ("LOW_MAX", low_res, low_t),
            (f"EXCLUDE_HIGH_MAX_{int(primary_frac*100)}", ex20["results"], ex20["trades"]),
        ]:
            row = portfolio_report(results, trades, spy_rets, label, rs, re)
            row["regime"] = name
            regime_rows.append(row)
    regimes = pd.DataFrame(regime_rows)
    # Regime dependence: Low-MAX sharpe positive in only one regime
    low_reg = regimes.loc[regimes["label"] == "LOW_MAX"]
    pos = (low_reg["net_sharpe"] > 0.1).sum()
    regime_flag = "REGIME_DEPENDENT" if pos <= 1 else "CROSS_REGIME_POSITIVE" if pos == 3 else "MIXED_REGIMES"

    # PHASE 6 — crisis
    windows = detect_spy_stress_windows(spy.loc[start:end])
    series_map = {
        "SPY": spy_rets.loc[start:end],
        "EW": ew_res.loc[start:end, "net_return"],
        "LOW_MAX": low_res.loc[start:end, "net_return"],
        f"EXCLUDE_{int(primary_frac*100)}": ex20["results"].loc[start:end, "net_return"],
    }
    crisis = crisis_metrics(windows, series_map, spy_rets.loc[start:end])

    # PHASE 7 — decision
    decision, rationale = _decide(
        value_map=value_map,
        exclusion_flag=exclusion_flag,
        residual_flag=residual_flag,
        regime_flag=regime_flag,
        benchmarks=benchmarks,
        exclusion_grid=exclusion_grid,
        crisis=crisis,
        anatomy=anatomy,
        config=config,
    )

    payload = {
        "parent_conclusion": config.raw["parent_conclusion"],
        "frozen": {
            "top_returns": config.top_returns,
            "lookback": config.lookback,
            "decile": config.portfolio_decile,
            "cap": config.max_portfolio_size,
            "one_way_bps": config.one_way_bps,
        },
        "data_status": config.raw["data_status"],
        "eval_window": {"start": str(start.date()), "end": str(end.date())},
        "style_notes": style_notes,
        "value_vs_spy": value_map,
        "exclusion_flag": exclusion_flag,
        "residual_flag": residual_flag,
        "regime_flag": regime_flag,
        "decision": decision,
        "rationale": rationale,
    }

    # Persist
    benchmarks.to_csv(run_dir / "low_max_benchmarks.csv", index=False)
    exclusion_grid.to_csv(run_dir / "max_exclusion_grid.csv", index=False)
    anatomy.to_csv(run_dir / "low_max_anatomy.csv", index=False)
    monthly_anatomy.to_csv(run_dir / "low_max_anatomy_monthly.csv", index=False)
    regimes.to_csv(run_dir / "low_max_regime.csv", index=False)
    residual.to_csv(run_dir / "low_max_residual.csv", index=False)
    crisis.to_csv(run_dir / "low_max_crisis.csv", index=False)
    windows.to_csv(run_dir / "stress_windows.csv", index=False)
    (run_dir / "decision.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    for name, frame in [
        ("low_max_benchmarks.csv", benchmarks),
        ("max_exclusion_grid.csv", exclusion_grid),
        ("low_max_anatomy.csv", anatomy),
        ("low_max_regime.csv", regimes),
    ]:
        frame.to_csv(config.reports_dir / name, index=False)

    write_reports(
        config.reports_dir / "low_max_defensive_research.md",
        run_dir / "low_max_defensive_research.md",
        payload,
        benchmarks,
        exclusion_grid,
        anatomy,
        residual,
        regimes,
        crisis,
    )
    return run_dir


def _decide(
    *,
    value_map,
    exclusion_flag,
    residual_flag,
    regime_flag,
    benchmarks,
    exclusion_grid,
    crisis,
    anatomy,
    config,
):
    rationale = []
    low = benchmarks.loc[benchmarks["label"] == "LOW_MAX"].iloc[0]
    spy = benchmarks.loc[benchmarks["label"] == "SPY_BH"].iloc[0]
    ew = benchmarks.loc[benchmarks["label"] == "EW_HIST_SP500"].iloc[0]

    rationale.append(
        f"LOW_MAX vs SPY: sharpe {low['net_sharpe']:.3f} vs {spy['net_sharpe']:.3f}; "
        f"cagr {low['net_cagr']:.3f} vs {spy['net_cagr']:.3f}; "
        f"maxDD {low['max_drawdown']:.3f} vs {spy['max_drawdown']:.3f}; beta {low['beta_spy']:.3f}."
    )
    rationale.append(
        f"LOW_MAX vs EW: sharpe {low['net_sharpe']:.3f} vs {ew['net_sharpe']:.3f}; "
        f"maxDD {low['max_drawdown']:.3f} vs {ew['max_drawdown']:.3f}."
    )
    rationale.append(f"Exclusion grid flag: {exclusion_flag}.")
    rationale.append(f"Residual after vol control: {residual_flag}.")
    rationale.append(f"Regime flag: {regime_flag}.")

    # Crisis: average Low-MAX crisis return vs SPY
    if not crisis.empty:
        pivot = crisis.pivot_table(index="window", columns="strategy", values="crisis_return", aggfunc="first")
        if "LOW_MAX" in pivot.columns and "SPY" in pivot.columns:
            better = (pivot["LOW_MAX"] > pivot["SPY"]).mean()
            rationale.append(f"Fraction of auto stress windows with LOW_MAX > SPY return: {better:.2f}.")

    if not anatomy.empty:
        vol_diff = anatomy.loc[anatomy["trait"] == "realized_vol_60d", "mean_diff"]
        if not vol_diff.empty:
            rationale.append(f"Anatomy: mean 60d vol diff (Low-MAX - universe) = {float(vol_diff.iloc[0]):.4f}.")

    # SPLV parity check (cheap low-vol proxy falsification)
    splv = benchmarks.loc[benchmarks["label"].str.startswith("SPLV")]
    if not splv.empty:
        s = splv.iloc[0]
        rationale.append(
            f"LOW_MAX vs SPLV: sharpe {low['net_sharpe']:.3f} vs {s['net_sharpe']:.3f}; "
            f"cagr {low['net_cagr']:.3f} vs {s['net_cagr']:.3f}; "
            f"vol {low['volatility']:.3f} vs {s['volatility']:.3f} — near-parity favors low-vol proxy."
        )

    # Classification — try to falsify first
    beats_simple = (
        low["net_sharpe"] > max(spy["net_sharpe"], ew["net_sharpe"]) + 0.05
        or (
            low["max_drawdown"] > max(spy["max_drawdown"], ew["max_drawdown"]) + 0.02
            and low["net_sharpe"] >= min(spy["net_sharpe"], ew["net_sharpe"]) - 0.05
        )
    )
    near_splv = False
    if not splv.empty:
        s = splv.iloc[0]
        near_splv = abs(low["net_sharpe"] - s["net_sharpe"]) < 0.05 and abs(low["volatility"] - s["volatility"]) < 0.02

    risk_filter_ok = exclusion_flag in {
        "MONOTONIC_IMPROVEMENT",
        "PARTIAL_IMPROVEMENT_NONMONOTONIC",
    } and residual_flag != "MAX_IS_VOLATILITY_PROXY"

    if residual_flag == "MAX_IS_VOLATILITY_PROXY" or near_splv:
        decision = "REJECT"
        rationale.append(
            "MAX exclusion adds no positive incremental Sharpe inside vol buckets, and/or Low-MAX "
            "matches SPLV — treat as volatility proxy, not a distinct MAX defensive signal."
        )
    elif not beats_simple and exclusion_flag in {"NO_SYSTEMATIC_IMPROVEMENT", "PARAMETER_SENSITIVE"}:
        decision = "REJECT"
        rationale.append("No clear outperformance vs SPY/EW and exclusion grid is weak or parameter-sensitive.")
    elif residual_flag == "INCREMENTAL_AFTER_VOL_CONTROL" and regime_flag == "CROSS_REGIME_POSITIVE" and beats_simple:
        decision = "PROMISING_LONG_ONLY_SIGNAL"
        rationale.append("Benchmark-adjusted edge survives regimes and vol control after costs.")
        base_class = "PROMISING_LONG_ONLY_SIGNAL"
    elif (
        value_map.get("C_lower_drawdown")
        or value_map.get("E_better_downside_protection")
        or value_map.get("D_lower_beta")
        or risk_filter_ok
    ) and residual_flag != "MAX_IS_VOLATILITY_PROXY":
        decision = "USEFUL_AS_RISK_FILTER"
        rationale.append("No independent alpha claim; MAX useful as defensive/exclusion risk filter if improvements are stable.")
        base_class = "USEFUL_AS_RISK_FILTER"
    else:
        decision = "REJECT"
        rationale.append("Evidence insufficient to support Low-MAX as defensive signal or risk filter.")
        base_class = "REJECT"

    if decision in {"USEFUL_AS_RISK_FILTER", "PROMISING_LONG_ONLY_SIGNAL"}:
        decision = "NEEDS_PAID_PIT_VALIDATION"
        rationale.append(
            f"Free evidence supports {base_class}; binding remaining gaps are PIT market cap / "
            "fundamentals / delisting — one-month Sharadar would be decision-relevant."
        )

    return decision, rationale
