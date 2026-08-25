"""Interaction attribution study: frozen grid vs external benchmarks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from .backtest import run_variant
from .config import DualMomentumConfig
from .data import cash_symbol_on
from .metrics import _stats, performance_report
from .signals import build_monthly_signal_panel, month_end_index, next_trading_day


STRESS_DEFAULT = {
    "gfc_2008": ("2007-10-01", "2009-03-31"),
    "covid_2020": ("2020-02-01", "2020-04-30"),
    "bear_2022": ("2022-01-01", "2022-12-31"),
}


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=["date", "signal_date", "turnover", "cost", "holdings", "reason"])


def _empty_targets() -> pd.DataFrame:
    return pd.DataFrame(columns=["signal_date", "execution_date", "symbol", "weight"])


def _finalize_equity(equity: pd.DataFrame, first_date: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    if first_date is not None:
        equity = equity.loc[equity.index >= first_date]
    equity = equity.copy()
    equity["equity_gross"] = (1 + equity["gross_return"]).cumprod()
    equity["equity_net"] = (1 + equity["net_return"]).cumprod()
    return equity


def run_buy_and_hold(
    closes: pd.DataFrame,
    symbol: str,
    *,
    start: Optional[pd.Timestamp] = None,
    name: Optional[str] = None,
) -> dict[str, Any]:
    series = closes[symbol].dropna()
    if start is not None:
        series = series.loc[series.index >= start]
    rets = series.pct_change(fill_method=None).fillna(0.0)
    equity = pd.DataFrame(
        {
            "gross_return": rets,
            "cost": 0.0,
            "net_return": rets,
            "exposure": 1.0,
            "n_holdings": 1,
        },
        index=rets.index,
    )
    equity = _finalize_equity(equity, rets.index.min())
    targets = pd.DataFrame(
        [
            {
                "signal_date": equity.index[0],
                "execution_date": equity.index[0],
                "symbol": symbol,
                "weight": 1.0,
            }
        ]
    )
    return {
        "variant": name or f"bh_{symbol.lower()}",
        "equity": equity,
        "targets": targets,
        "trades": _empty_trades(),
        "monthly_scores": pd.DataFrame(),
        "audit": pd.DataFrame(),
        "cash_switches": pd.DataFrame(),
        "one_way_bps": 0.0,
    }


def run_sixty_forty(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    config: DualMomentumConfig,
    *,
    equity_symbol: str = "SPY",
    bond_symbol: str = "IEF",
    equity_weight: float = 0.6,
    start: Optional[pd.Timestamp] = None,
) -> dict[str, Any]:
    """Month-end signal / next-open rebalance to fixed 60/40."""
    cost_bps = float(config.raw["costs"]["one_way_bps"])
    common = opens.index.intersection(closes.index).sort_values()
    if start is not None:
        common = common[common >= start]
    opens = opens.reindex(common)
    closes = closes.reindex(common)
    month_ends = month_end_index(common)
    execute_map = {}
    for signal_date in month_ends:
        exec_date = next_trading_day(common, signal_date)
        if exec_date is not None:
            execute_map[exec_date] = pd.Timestamp(signal_date)

    target = pd.Series({equity_symbol: equity_weight, bond_symbol: 1.0 - equity_weight})
    weights = pd.Series(dtype=float)
    pending: Optional[pd.Series] = None
    pending_signal = None
    rows, targets, trades = [], [], []
    previous_close = None
    signal_dates = set(month_ends)

    for date in common:
        open_prices = opens.loc[date]
        close_prices = closes.loc[date]
        gross = 0.0
        cost = 0.0
        if previous_close is not None and not weights.empty:
            overnight = (open_prices / previous_close - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            gross += float((weights.reindex(overnight.index, fill_value=0.0) * overnight).sum())
        if date in execute_map and pending is not None:
            turnover = float(pending.sub(weights, fill_value=0.0).abs().sum())
            trade_cost = turnover * cost_bps / 10_000
            cost += trade_cost
            trades.append(
                {
                    "date": date,
                    "signal_date": pending_signal,
                    "turnover": turnover,
                    "cost": trade_cost,
                    "holdings": 2,
                    "reason": "next_open_rebalance",
                }
            )
            for symbol, weight in pending.items():
                targets.append(
                    {
                        "signal_date": pending_signal,
                        "execution_date": date,
                        "symbol": symbol,
                        "weight": float(weight),
                    }
                )
            weights = pending
            pending = None
        if not weights.empty:
            intraday = (close_prices / open_prices - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            gross += float((weights.reindex(intraday.index, fill_value=0.0) * intraday).sum())
        if date in signal_dates:
            pending = target.copy()
            pending_signal = date
        rows.append(
            {
                "date": date,
                "gross_return": gross,
                "cost": cost,
                "net_return": gross - cost,
                "exposure": float(weights.get(equity_symbol, 0.0)) if not weights.empty else 0.0,
                "n_holdings": int((weights > 0).sum()) if not weights.empty else 0,
            }
        )
        previous_close = close_prices

    equity = pd.DataFrame(rows).set_index("date")
    if trades:
        equity = equity.loc[equity.index >= pd.Timestamp(min(t["date"] for t in trades))]
    equity = _finalize_equity(equity)
    return {
        "variant": "sixty_forty",
        "equity": equity,
        "targets": pd.DataFrame(targets),
        "trades": pd.DataFrame(trades) if trades else _empty_trades(),
        "monthly_scores": pd.DataFrame(),
        "audit": pd.DataFrame(),
        "cash_switches": pd.DataFrame(),
        "one_way_bps": cost_bps,
    }


def run_spy_ma10(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    config: DualMomentumConfig,
    *,
    start: Optional[pd.Timestamp] = None,
) -> dict[str, Any]:
    """100% SPY when above 10-month SMA else 100% cash; month-end / next-open."""
    cost_bps = float(config.raw["costs"]["one_way_bps"])
    common = opens.index.intersection(closes.index).sort_values()
    if start is not None:
        common = common[common >= start]
    opens = opens.reindex(common)
    closes = closes.reindex(common)
    panel = build_monthly_signal_panel(
        closes,
        risk_symbols=["SPY"],
        weight_5m=float(config.raw["momentum"]["weight_5m"]),
        weight_12m=float(config.raw["momentum"]["weight_12m"]),
        sma_months=int(config.raw["trend_filter"]["month_sma"]),
        vol_lookback=int(config.raw["volatility"]["lookback_days"]),
        vol_min_obs=int(config.raw["volatility"]["min_observations"]),
    )
    month_ends = month_end_index(common)
    execute_map = {}
    for signal_date in month_ends:
        exec_date = next_trading_day(common, signal_date)
        if exec_date is not None:
            execute_map[exec_date] = pd.Timestamp(signal_date)

    weights = pd.Series(dtype=float)
    pending: Optional[pd.Series] = None
    pending_signal = None
    rows, targets, trades = [], [], []
    previous_close = None
    previous_cash = None
    cash_switches = []
    signal_dates = set(month_ends)

    for date in common:
        open_prices = opens.loc[date]
        close_prices = closes.loc[date]
        gross = 0.0
        cost = 0.0
        if previous_close is not None and not weights.empty:
            overnight = (open_prices / previous_close - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            gross += float((weights.reindex(overnight.index, fill_value=0.0) * overnight).sum())
        if date in execute_map and pending is not None:
            turnover = float(pending.sub(weights, fill_value=0.0).abs().sum())
            trade_cost = turnover * cost_bps / 10_000
            cost += trade_cost
            trades.append(
                {
                    "date": date,
                    "signal_date": pending_signal,
                    "turnover": turnover,
                    "cost": trade_cost,
                    "holdings": int((pending > 0).sum()),
                    "reason": "next_open_rebalance",
                }
            )
            for symbol, weight in pending.items():
                targets.append(
                    {
                        "signal_date": pending_signal,
                        "execution_date": date,
                        "symbol": symbol,
                        "weight": float(weight),
                    }
                )
            weights = pending
            pending = None
        if not weights.empty:
            intraday = (close_prices / open_prices - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            gross += float((weights.reindex(intraday.index, fill_value=0.0) * intraday).sum())
        if date in signal_dates:
            cash = cash_symbol_on(date, config, closes)
            if previous_cash is not None and cash != previous_cash:
                cash_switches.append({"date": date, "from": previous_cash, "to": cash})
            previous_cash = cash
            day = panel[panel["date"] == date]
            above = bool(day.iloc[0]["above_ma"]) if len(day) else False
            pending = pd.Series({"SPY": 1.0} if above else {cash: 1.0})
            pending_signal = date
        rows.append(
            {
                "date": date,
                "gross_return": gross,
                "cost": cost,
                "net_return": gross - cost,
                "exposure": float(weights.get("SPY", 0.0)) if not weights.empty else 0.0,
                "n_holdings": int((weights > 0).sum()) if not weights.empty else 0,
            }
        )
        previous_close = close_prices

    equity = pd.DataFrame(rows).set_index("date")
    if trades:
        equity = equity.loc[equity.index >= pd.Timestamp(min(t["date"] for t in trades))]
    equity = _finalize_equity(equity)
    return {
        "variant": "spy_ma10",
        "equity": equity,
        "targets": pd.DataFrame(targets),
        "trades": pd.DataFrame(trades) if trades else _empty_trades(),
        "monthly_scores": panel,
        "audit": pd.DataFrame(),
        "cash_switches": pd.DataFrame(cash_switches),
        "one_way_bps": cost_bps,
    }


def holding_weight_stats(targets: pd.DataFrame) -> dict[str, float]:
    if targets is None or targets.empty:
        return {
            "avg_weight_QQQ": 0.0,
            "avg_weight_SPY": 0.0,
            "avg_weight_cash": 0.0,
            "max_single_weight": 0.0,
            "qqq_held_pct": np.nan,
            "spy_held_pct": np.nan,
            "cash_only_pct": np.nan,
        }
    pivot = targets.pivot_table(index="signal_date", columns="symbol", values="weight", aggfunc="sum").fillna(0.0)
    cash_cols = [c for c in pivot.columns if c in {"SGOV", "BIL"}]
    cash = pivot[cash_cols].sum(axis=1) if cash_cols else pd.Series(0.0, index=pivot.index)
    risk = pivot.drop(columns=cash_cols, errors="ignore")
    return {
        "avg_weight_QQQ": float(pivot["QQQ"].mean()) if "QQQ" in pivot.columns else 0.0,
        "avg_weight_SPY": float(pivot["SPY"].mean()) if "SPY" in pivot.columns else 0.0,
        "avg_weight_cash": float(cash.mean()),
        "max_single_weight": float(risk.max(axis=1).max()) if not risk.empty else 0.0,
        "max_cash_weight": float(cash.max()) if len(cash) else 0.0,
        "qqq_held_pct": float((pivot["QQQ"] > 1e-9).mean()) if "QQQ" in pivot.columns else 0.0,
        "spy_held_pct": float((pivot["SPY"] > 1e-9).mean()) if "SPY" in pivot.columns else 0.0,
        "cash_only_pct": float((cash >= 1.0 - 1e-9).mean()),
    }


def yearly_returns(equity: pd.DataFrame) -> pd.Series:
    net = equity["net_return"]
    return (1 + net).groupby(net.index.year).prod() - 1


def rolling_sharpe(equity: pd.DataFrame, window_days: int = 252 * 3) -> pd.Series:
    rets = equity["net_return"]
    mean = rets.rolling(window_days, min_periods=window_days // 2).mean()
    std = rets.rolling(window_days, min_periods=window_days // 2).std(ddof=1)
    return (mean / std * np.sqrt(252)).replace([np.inf, -np.inf], np.nan)


def worst_trailing_return(equity: pd.DataFrame, window_days: int = 252) -> float:
    rets = equity["net_return"]
    if len(rets) < window_days:
        return float((1 + rets).prod() - 1) if len(rets) else np.nan
    trail = (1 + rets).rolling(window_days).apply(np.prod, raw=True) - 1
    return float(trail.min())


def window_total_return(equity: pd.DataFrame, start: str, end: str) -> float:
    slice_ = equity.loc[start:end]
    if slice_.empty:
        return np.nan
    return float((1 + slice_["net_return"]).prod() - 1)


def relative_stats(strategy: pd.DataFrame, benchmark: pd.DataFrame) -> dict[str, float]:
    aligned = pd.concat(
        [strategy["net_return"].rename("s"), benchmark["net_return"].rename("b")],
        axis=1,
    ).dropna()
    if aligned.empty:
        return {"rel_cagr": np.nan, "rel_sharpe": np.nan, "excess_cagr": np.nan}
    s_stats = _stats(aligned["s"])
    b_stats = _stats(aligned["b"])
    excess = aligned["s"] - aligned["b"]
    return {
        "rel_cagr": s_stats["cagr"] - b_stats["cagr"],
        "rel_sharpe": s_stats["sharpe"] - b_stats["sharpe"],
        "excess_cagr": s_stats["cagr"] - b_stats["cagr"],
        "benchmark_cagr": b_stats["cagr"],
        "benchmark_sharpe": b_stats["sharpe"],
        "benchmark_max_drawdown": b_stats["max_drawdown"],
    }


def attribution_bundle(
    result: dict[str, Any],
    *,
    reference_equity: Optional[pd.DataFrame],
    benchmarks: dict[str, dict[str, Any]],
    research_windows: dict,
    stress_windows: dict,
) -> dict[str, Any]:
    equity = result["equity"]
    trades = result["trades"]
    targets = result["targets"]
    base = performance_report(
        equity,
        trades,
        targets,
        # equity_net is a wealth index; pct_change recovers daily returns for relative stats.
        benchmarks["bh_spy"]["equity"]["equity_net"],
    )
    holdings = holding_weight_stats(targets)
    years = yearly_returns(equity)
    ref_years = yearly_returns(reference_equity) if reference_equity is not None else None
    year_delta = (years - ref_years).dropna() if ref_years is not None else pd.Series(dtype=float)
    roll = rolling_sharpe(equity)
    ref_roll = rolling_sharpe(reference_equity) if reference_equity is not None else None
    roll_delta = (roll - ref_roll).dropna() if ref_roll is not None else pd.Series(dtype=float)
    pos_year = float((year_delta > 0).mean()) if len(year_delta) else np.nan
    pos_roll = float((roll_delta > 0).mean()) if len(roll_delta) else np.nan

    stress = {
        name: window_total_return(equity, bounds[0], bounds[1])
        for name, bounds in stress_windows.items()
    }
    oos = research_windows.get("locked_oos", ["2024-01-01", "2026-06-30"])
    oos_slice = equity.loc[oos[0] : oos[1]]
    oos_stats = _stats(oos_slice["net_return"]) if not oos_slice.empty else _stats(pd.Series(dtype=float))

    rel = {
        name: relative_stats(equity, payload["equity"])
        for name, payload in benchmarks.items()
        if name in {"bh_spy", "bh_qqq", "sixty_forty"}
    }

    return {
        "variant": result["variant"],
        "summary": {
            "net_cagr": base["net_cagr"],
            "net_volatility": base["net_volatility"],
            "net_sharpe": base["net_sharpe"],
            "net_max_drawdown": base["net_max_drawdown"],
            "annualized_turnover": base["annualized_turnover"],
            "cost_total": base["cost_total"],
            "worst_12m_return": worst_trailing_return(equity, 252),
            "oos_cagr": oos_stats["cagr"],
            "oos_sharpe": oos_stats["sharpe"],
            "oos_max_drawdown": oos_stats["max_drawdown"],
            "positive_year_delta_vs_A": pos_year,
            "positive_roll3y_sharpe_delta_vs_A": pos_roll,
            **holdings,
            **{f"stress_{k}": v for k, v in stress.items()},
            **{f"vs_{k}_{mk}": mv for k, stats in rel.items() for mk, mv in stats.items()},
        },
        "yearly_returns": years.to_dict(),
        "yearly_delta_vs_A": year_delta.to_dict() if len(year_delta) else {},
        "rolling_3y_sharpe": {str(k.date()): float(v) for k, v in roll.dropna().items()},
        "stress": stress,
        "relative": rel,
    }


def align_start(results: dict[str, dict[str, Any]]) -> pd.Timestamp:
    starts = [payload["equity"].index.min() for payload in results.values() if not payload["equity"].empty]
    return max(starts)


def trim_result(result: dict[str, Any], start: pd.Timestamp) -> dict[str, Any]:
    out = dict(result)
    eq = result["equity"].loc[result["equity"].index >= start].copy()
    out["equity"] = _finalize_equity(eq)
    if not result["targets"].empty and "execution_date" in result["targets"]:
        out["targets"] = result["targets"][result["targets"]["execution_date"] >= start].copy()
    if not result["trades"].empty:
        out["trades"] = result["trades"][result["trades"]["date"] >= start].copy()
    return out


def run_attribution(config: DualMomentumConfig, opens: pd.DataFrame, closes: pd.DataFrame) -> dict[str, Any]:
    attr = config.raw["attribution"]
    experiments = list(attr["experiments"])
    bench_names = list(attr["benchmarks"])
    ref_name = attr["reference"]
    stress = {
        k: tuple(v) for k, v in (config.raw.get("stress_windows") or STRESS_DEFAULT).items()
    }
    research_windows = config.raw["research_windows"]

    results: dict[str, dict[str, Any]] = {}
    for name in experiments:
        results[name] = run_variant(opens, closes, config, name)

    # Strategy-style benchmarks from frozen variants
    for name in ["simple_dual_mom", "ew_trend"]:
        if name in bench_names:
            results[name] = run_variant(opens, closes, config, name)

    # Align sample to latest common strategy start among attribution experiments first
    strategy_start = align_start({k: results[k] for k in experiments})
    results["bh_spy"] = run_buy_and_hold(closes, "SPY", start=strategy_start, name="bh_spy")
    results["bh_qqq"] = run_buy_and_hold(closes, "QQQ", start=strategy_start, name="bh_qqq")
    results["sixty_forty"] = run_sixty_forty(opens, closes, config, start=strategy_start)
    results["spy_ma10"] = run_spy_ma10(opens, closes, config, start=strategy_start)

    # Re-trim everything to common start
    common_start = align_start(results)
    results = {name: trim_result(payload, common_start) for name, payload in results.items()}

    ref_equity = results[ref_name]["equity"]
    benchmarks = {name: results[name] for name in ["bh_spy", "bh_qqq", "sixty_forty"]}

    bundles = {}
    for name, payload in results.items():
        bundles[name] = attribution_bundle(
            payload,
            reference_equity=None if name == ref_name else ref_equity,
            benchmarks=benchmarks,
            research_windows=research_windows,
            stress_windows=stress,
        )
        # Reference vs itself: yearly delta empty is fine
        if name == ref_name:
            bundles[name]["summary"]["positive_year_delta_vs_A"] = np.nan
            bundles[name]["summary"]["positive_roll3y_sharpe_delta_vs_A"] = np.nan

    return {
        "common_start": str(common_start.date()),
        "reference": ref_name,
        "results": results,
        "bundles": bundles,
        "experiments": experiments,
        "benchmarks": bench_names,
    }


def write_attribution_report(directory: Path, study: dict[str, Any], promote_to: Optional[Path] = None) -> Path:
    bundles = study["bundles"]
    experiments = study["experiments"]
    benchmarks = study["benchmarks"]
    ref = study["reference"]

    # Persist tables
    summary_rows = []
    for name in experiments + [b for b in benchmarks if b in bundles]:
        row = {"variant": name, **bundles[name]["summary"]}
        summary_rows.append(row)
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(directory / "attribution_summary.csv", index=False)

    yearly = pd.DataFrame({name: bundles[name]["yearly_returns"] for name in experiments})
    yearly.index.name = "year"
    yearly.to_csv(directory / "yearly_returns.csv")
    yearly_delta = pd.DataFrame(
        {name: bundles[name]["yearly_delta_vs_A"] for name in experiments if name != ref}
    )
    if not yearly_delta.empty:
        yearly_delta.index.name = "year"
        yearly_delta.to_csv(directory / "yearly_delta_vs_A.csv")

    (directory / "attribution_bundles.json").write_text(
        json.dumps(
            {
                "common_start": study["common_start"],
                "reference": ref,
                "summaries": {k: v["summary"] for k, v in bundles.items()},
                "yearly_returns": {k: v["yearly_returns"] for k, v in bundles.items()},
                "yearly_delta_vs_A": {k: v["yearly_delta_vs_A"] for k, v in bundles.items()},
                "stress": {k: v["stress"] for k, v in bundles.items()},
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    for name, payload in study["results"].items():
        payload["equity"].to_csv(directory / f"{name}_equity.csv")
        if not payload["targets"].empty:
            payload["targets"].to_csv(directory / f"{name}_targets.csv", index=False)
        if not payload["trades"].empty:
            payload["trades"].to_csv(directory / f"{name}_trades.csv", index=False)

    def pct(x):
        if x is None or (isinstance(x, float) and (x != x)):
            return "n/a"
        return f"{x:.2%}"

    def num(x):
        if x is None or (isinstance(x, float) and (x != x)):
            return "n/a"
        return f"{x:.2f}"

    lines = [
        "# Interaction Attribution",
        "",
        f"- Common sample start: `{study['common_start']}`",
        f"- Reference (A): `{ref}` — vol-adjusted dual momentum, **no hysteresis**",
        f"- Frozen one-way cost: from config (default 5 bp)",
        "- Regime sizing (B) excluded by design.",
        "",
        "## Experiment grid vs A",
        "",
        "| Variant | Net CAGR | Sharpe | MaxDD | vs A CAGR | Ann. TO | Cost | Avg QQQ w | Avg SPY w | Avg cash w | Max w | Worst 12M | OOS Sharpe | +year vs A | +roll3y vs A |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    ref_cagr = bundles[ref]["summary"]["net_cagr"]
    for name in experiments:
        s = bundles[name]["summary"]
        delta = (s["net_cagr"] - ref_cagr) if name != ref else 0.0
        lines.append(
            "| {name} | {cagr} | {sh} | {dd} | {dc} | {to} | {cost} | {qqq} | {spy} | {cash} | {mw} | {w12} | {oos} | {py} | {pr} |".format(
                name=name.replace("attribution_", ""),
                cagr=pct(s["net_cagr"]),
                sh=num(s["net_sharpe"]),
                dd=pct(s["net_max_drawdown"]),
                dc=pct(delta),
                to=num(s["annualized_turnover"]),
                cost=num(s["cost_total"]),
                qqq=pct(s["avg_weight_QQQ"]),
                spy=pct(s["avg_weight_SPY"]),
                cash=pct(s["avg_weight_cash"]),
                mw=pct(s["max_single_weight"]),
                w12=pct(s["worst_12m_return"]),
                oos=num(s["oos_sharpe"]),
                py=pct(s["positive_year_delta_vs_A"]),
                pr=pct(s["positive_roll3y_sharpe_delta_vs_A"]),
            )
        )

    lines.extend(
        [
            "",
            "## External benchmarks (same sample)",
            "",
            "| Benchmark | Net CAGR | Sharpe | MaxDD | Worst 12M | Notes |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    notes = {
        "bh_spy": "Buy & hold SPY",
        "bh_qqq": "Buy & hold QQQ",
        "sixty_forty": "60% SPY + 40% IEF, monthly rebalance",
        "spy_ma10": "SPY if above 10M SMA else cash",
        "simple_dual_mom": "Raw dual mom Top2, no vol adj, no hyst",
        "ew_trend": "Equal-weight risk assets above 10M SMA",
    }
    for name in benchmarks:
        s = bundles[name]["summary"]
        lines.append(
            f"| {name} | {pct(s['net_cagr'])} | {num(s['net_sharpe'])} | {pct(s['net_max_drawdown'])} | {pct(s['worst_12m_return'])} | {notes.get(name, '')} |"
        )

    lines.extend(["", "## Stress windows (total return)", ""])
    stress_names = list(next(iter(bundles.values()))["stress"].keys())
    header = "| Variant | " + " | ".join(stress_names) + " |"
    sep = "|---|" + "|".join(["---:"] * len(stress_names)) + "|"
    lines.extend([header, sep])
    for name in experiments + benchmarks:
        s = bundles[name]["stress"]
        lines.append("| {name} | {vals} |".format(name=name, vals=" | ".join(pct(s[k]) for k in stress_names)))

    lines.extend(
        [
            "",
            "## Continue? Positioning check",
            "",
            f"- A (`{ref}`) net CAGR {pct(bundles[ref]['summary']['net_cagr'])} vs SPY {pct(bundles['bh_spy']['summary']['net_cagr'])} vs QQQ {pct(bundles['bh_qqq']['summary']['net_cagr'])}.",
            f"- A MaxDD {pct(bundles[ref]['summary']['net_max_drawdown'])} vs SPY {pct(bundles['bh_spy']['summary']['net_max_drawdown'])} vs QQQ {pct(bundles['bh_qqq']['summary']['net_max_drawdown'])}.",
            "- If A lags SPY/QQQ on CAGR but cuts drawdown materially, treat it as a **drawdown-managed allocation** sleeve, not an absolute-return alpha chase.",
            "",
            "## Yearly returns (experiments)",
            "",
            "See `yearly_returns.csv` and `yearly_delta_vs_A.csv` in this run directory.",
            "",
        ]
    )

    path = directory / "interaction_attribution.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if promote_to is not None:
        promote_to.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        summary.to_csv(promote_to.parent / "interaction_attribution_summary.csv", index=False)
    return path
