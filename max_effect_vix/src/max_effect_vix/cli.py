"""Command line workflow for free pilot and historical-S&P500 validation."""
from __future__ import annotations

import argparse
import json
from typing import Optional

import pandas as pd

from .artifacts import new_run_directory
from .backtest import run_backtest
from .config import load_config
from .data import (
    PILOT_SYMBOLS,
    audit_cache,
    current_universe,
    fetch_current_sp500_universe,
    fetch_pilot,
    load_benchmark,
    load_pilot,
)
from .factors import max_factor, monthly_signal_dates
from .metrics import performance_report, window_reports
from .purchase_gate import run_purchase_gate
from .reporting import write_pit_validation_report
from .robustness import run_grid
from .status import research_status
from .universe_provider import (
    fetch_historical_sp500_events,
    load_historical_provider,
    membership_audit,
)
from .validation import (
    factor_regression,
    fama_macbeth,
    load_ken_french_factors,
    monthly_ic_table,
    summarize_fama_macbeth,
)

LIMITATIONS = [
    "Wikipedia S&P 500 change history is incomplete.",
    "SURVIVORSHIP_BIAS remains REDUCED_NOT_ELIMINATED, not eliminated.",
    "PIT_VALIDATED is false; no CRSP/Compustat point-in-time fundamentals.",
    "Size neutralization is BLOCKED_BY_PIT_MARKET_CAP.",
    "Index exit is not a CRSP delisting return; DELISTING_RETURN=UNAVAILABLE.",
    "Yahoo prices omit a complete delisting file and may miss dead tickers.",
]


def _write_summary(directory, metrics: dict, variant: str, status: dict) -> None:
    lines = [
        "# MAX anomaly result",
        "",
        f"- DATA_TIER: `{status['DATA_TIER']}`",
        f"- SURVIVORSHIP_BIAS: `{status['SURVIVORSHIP_BIAS']}`",
        f"- PIT_VALIDATED: `{status['PIT_VALIDATED']}`",
        "",
        f"Variant: `{variant}`",
        "",
        *[f"- {key}: {value}" for key, value in metrics.items()],
    ]
    (directory / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_fetch(args: argparse.Namespace) -> int:
    config = load_config()
    if args.full and (config.cache_dir / "sp500_membership_events.parquet").exists():
        provider = load_historical_provider(config.cache_dir)
        symbols = provider.all_symbols()
    else:
        symbols = (
            current_universe(config.cache_dir, config.raw["free_data"]["fallback_symbols"])
            if args.full
            else PILOT_SYMBOLS[: args.limit]
        )
    manifest = fetch_pilot(config.cache_dir, config.raw["free_data"]["start"], symbols)
    print(json.dumps(manifest, indent=2))
    return 0 if not manifest["failures"] else 2


def cmd_universe(_: argparse.Namespace) -> int:
    config = load_config()
    symbols = fetch_current_sp500_universe(config.cache_dir)
    print(json.dumps({"symbols": len(symbols), **research_status(False)}, indent=2))
    return 0


def cmd_universe_hist(_: argparse.Namespace) -> int:
    config = load_config()
    events = fetch_historical_sp500_events(config.cache_dir)
    provider = load_historical_provider(config.cache_dir)
    print(
        json.dumps(
            {
                "events": len(events),
                "symbols": len(provider.all_symbols()),
                **provider.status(),
            },
            indent=2,
        )
    )
    return 0


def cmd_membership_audit(_: argparse.Namespace) -> int:
    config = load_config()
    provider = load_historical_provider(config.cache_dir)
    dates = pd.date_range(config.raw["free_data"]["start"], periods=24, freq="MS")
    frame = membership_audit(provider, list(dates))
    directory = new_run_directory(
        config, "membership_audit", provider.status()["DATA_TIER"], provider.status()
    )
    frame.to_csv(directory / "coverage_audit.csv", index=False)
    exits = provider.index_exits(dates.min(), pd.Timestamp.today())
    exits.to_csv(directory / "index_exit_events.csv", index=False)
    print(directory)
    return 0


def cmd_audit(_: argparse.Namespace) -> int:
    print(json.dumps(audit_cache(load_config().cache_dir), indent=2))
    return 0


def _membership_fn(config):
    path = config.cache_dir / "sp500_membership_events.parquet"
    if not path.exists():
        return None, research_status(False)
    provider = load_historical_provider(config.cache_dir)
    return provider.symbols_on, provider.status()


def _one_run(variant: str = "raw", one_way_bps: Optional[float] = None):
    config = load_config()
    opens, closes, volumes, vix = load_pilot(config.cache_dir)
    benchmark = load_benchmark(config.cache_dir, config.raw["benchmark"])
    membership_on, status = _membership_fn(config)
    run_dir = new_run_directory(config, f"run_{variant}", status["DATA_TIER"], status)
    kwargs = config.raw
    results, holdings, trades, exits = run_backtest(
        opens,
        closes,
        volumes,
        vix,
        lookback=kwargs["signal_lookback_days"],
        top_returns=kwargs["top_returns"],
        min_dollar_volume=kwargs["min_dollar_volume"],
        portfolio_decile=kwargs["portfolio_decile"],
        max_portfolio_size=kwargs["max_portfolio_size"],
        vix_mode="none",
        one_way_bps=one_way_bps if one_way_bps is not None else kwargs["costs"]["one_way_bps"],
        annual_margin_rate=kwargs["costs"]["annual_margin_rate"],
        benchmark=benchmark,
        factor_variant=variant,
        volatility_lookback_days=kwargs["neutralization"]["volatility_lookback_days"],
        beta_lookback_days=kwargs["neutralization"]["beta_lookback_days"],
        beta_min_observations=kwargs["neutralization"]["beta_min_observations"],
        winsor_limits=tuple(kwargs["neutralization"]["winsor_limits"]),
        annual_spy_borrow_rate=kwargs["costs"]["annual_spy_borrow_rate"],
        membership_on=membership_on,
    )
    results.to_csv(run_dir / "daily_results.csv")
    holdings.to_csv(run_dir / "holdings.csv", index=False)
    trades.to_csv(run_dir / "trades.csv", index=False)
    exits.to_csv(run_dir / "index_exit_events.csv", index=False)
    metrics = performance_report(results, trades, benchmark)
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (run_dir / "metrics_by_window.json").write_text(
        json.dumps(window_reports(results, trades, benchmark, kwargs["research_windows"]), indent=2),
        encoding="utf-8",
    )
    _write_summary(run_dir, metrics, variant, status)
    return run_dir


def cmd_run(args: argparse.Namespace) -> int:
    print(_one_run(args.variant))
    return 0


def cmd_robustness(_: argparse.Namespace) -> int:
    config = load_config()
    opens, closes, volumes, vix = load_pilot(config.cache_dir)
    benchmark = load_benchmark(config.cache_dir, config.raw["benchmark"])
    membership_on, status = _membership_fn(config)
    directory = new_run_directory(config, "robustness", status["DATA_TIER"], status)
    frame = run_grid(
        opens,
        closes,
        volumes,
        vix,
        benchmark,
        config.raw,
        config.raw["costs"]["one_way_bps"],
        membership_on=membership_on,
    )
    frame.to_csv(directory / "robustness.csv", index=False)
    frame.to_csv(config.reports_dir / "max_anomaly_robustness.csv", index=False)
    (directory / "summary.md").write_text(
        f"# MAX robustness grid\n\nDATA_TIER=`{status['DATA_TIER']}`; "
        f"SURVIVORSHIP_BIAS=`{status['SURVIVORSHIP_BIAS']}`; PIT_VALIDATED=`{status['PIT_VALIDATED']}`.\n",
        encoding="utf-8",
    )
    print(directory)
    return 0


def cmd_cost_stress(_: argparse.Namespace) -> int:
    config = load_config()
    rows = []
    for bps in config.raw["costs"]["stress_one_way_bps"]:
        path = _one_run("raw", bps)
        rows.append({"one_way_bps": bps, **json.loads((path / "metrics.json").read_text(encoding="utf-8"))})
    _, status = _membership_fn(config)
    directory = new_run_directory(config, "cost_stress", status["DATA_TIER"], status)
    pd.DataFrame(rows).to_csv(directory / "cost_stress.csv", index=False)
    print(directory)
    return 0


def cmd_validate_hist(_: argparse.Namespace) -> int:
    config = load_config()
    provider = load_historical_provider(config.cache_dir)
    opens, closes, volumes, vix = load_pilot(config.cache_dir)
    benchmark = load_benchmark(config.cache_dir, config.raw["benchmark"])
    status = provider.status()
    directory = new_run_directory(config, "validate_hist", status["DATA_TIER"], status)
    results, holdings, trades, exits = run_backtest(
        opens,
        closes,
        volumes,
        vix,
        lookback=config.raw["signal_lookback_days"],
        top_returns=config.raw["top_returns"],
        min_dollar_volume=config.raw["min_dollar_volume"],
        portfolio_decile=config.raw["portfolio_decile"],
        max_portfolio_size=config.raw["max_portfolio_size"],
        vix_mode="none",
        one_way_bps=config.raw["costs"]["one_way_bps"],
        annual_margin_rate=config.raw["costs"]["annual_margin_rate"],
        benchmark=benchmark,
        factor_variant="raw",
        volatility_lookback_days=config.raw["neutralization"]["volatility_lookback_days"],
        beta_lookback_days=config.raw["neutralization"]["beta_lookback_days"],
        beta_min_observations=config.raw["neutralization"]["beta_min_observations"],
        winsor_limits=tuple(config.raw["neutralization"]["winsor_limits"]),
        annual_spy_borrow_rate=config.raw["costs"]["annual_spy_borrow_rate"],
        membership_on=provider.symbols_on,
    )
    results.to_csv(directory / "daily_results.csv")
    holdings.to_csv(directory / "holdings.csv", index=False)
    trades.to_csv(directory / "trades.csv", index=False)
    metrics = performance_report(results, trades, benchmark)

    # Cross-sectional IC / Fama-MacBeth on formation dates.
    returns = closes.pct_change(fill_method=None)
    signals = returns.apply(max_factor, lookback=config.raw["signal_lookback_days"], top_returns=config.raw["top_returns"])
    signal_dates = monthly_signal_dates(closes.index)
    # Forward month return: close[t] -> close[next signal]
    forward = pd.DataFrame(index=signal_dates, columns=closes.columns, dtype=float)
    ordered = list(signal_dates)
    for idx, date in enumerate(ordered[:-1]):
        nxt = ordered[idx + 1]
        forward.loc[date] = closes.loc[nxt] / closes.loc[date] - 1
    signal_panel = signals.loc[ordered[:-1]]
    # Mask non-members.
    for date in signal_panel.index:
        members = provider.symbols_on(date)
        signal_panel.loc[date] = signal_panel.loc[date].where(signal_panel.columns.isin(members))
        forward.loc[date] = forward.loc[date].where(forward.columns.isin(members))
    ic_table = monthly_ic_table(signal_panel, forward)
    fm = fama_macbeth(signal_panel, forward)
    fm_summary = summarize_fama_macbeth(fm)
    fm.to_csv(directory / "fama_macbeth.csv", index=False)

    monthly = results["net_return"].resample("ME").apply(lambda x: (1 + x).prod() - 1)
    factors = load_ken_french_factors()
    if not factors.empty and "RF" in factors.columns:
        excess = monthly - factors.reindex(monthly.index)["RF"].fillna(0.0)
        factor_result = factor_regression(excess, factors)
    else:
        factor_result = {
            "alpha": None,
            "alpha_annualized": None,
            "t_stat": None,
            "n": 0,
            "qmj_status": "NOT_AVAILABLE",
            "loadings": {},
            "note": "Ken French factors unavailable in this environment",
        }
    pd.DataFrame([{"factor": key, "loading": value} for key, value in factor_result.get("loadings", {}).items()]).to_csv(
        directory / "factor_regressions.csv", index=False
    )

    dates = pd.date_range(config.raw["free_data"]["start"], periods=24, freq="MS")
    audit = membership_audit(provider, list(dates))
    report = write_pit_validation_report(
        directory,
        metrics=metrics,
        fama_macbeth_summary=fm_summary,
        factor_result=factor_result,
        membership_audit=audit,
        exit_events=exits if not exits.empty else provider.index_exits(dates.min(), pd.Timestamp.today()),
        ic_table=ic_table,
        limitations=LIMITATIONS,
    )
    # Promote a stable copy for the research library.
    stable = config.reports_dir / "max_anomaly_pit_validation.md"
    stable.write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
    print(directory)
    return 0


def cmd_pit_report(_: argparse.Namespace) -> int:
    return cmd_validate_hist(_)


def cmd_purchase_gate(_: argparse.Namespace) -> int:
    print(run_purchase_gate())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="max-effect-vix")
    sub = parser.add_subparsers(dest="command", required=True)
    universe = sub.add_parser("universe", help="Cache current S&P 500 snapshot (biased pilot)")
    universe.set_defaults(func=cmd_universe)
    universe_hist = sub.add_parser("universe-hist", help="Cache historical S&P 500 membership events")
    universe_hist.set_defaults(func=cmd_universe_hist)
    membership = sub.add_parser("membership-audit", help="Audit historical membership counts")
    membership.set_defaults(func=cmd_membership_audit)
    fetch = sub.add_parser("fetch", help="Cache free-data pilot bars")
    fetch.add_argument("--limit", type=int, default=8)
    fetch.add_argument("--full", action="store_true")
    fetch.set_defaults(func=cmd_fetch)
    audit = sub.add_parser("audit", help="Audit cached bars and source gaps")
    audit.set_defaults(func=cmd_audit)
    run = sub.add_parser("run", help="Run one MAX anomaly variant")
    run.add_argument("--variant", choices=["raw", "vol_neutral", "beta_neutral", "beta_hedged"], default="raw")
    run.set_defaults(func=cmd_run)
    robustness = sub.add_parser("robustness", help="Run frozen MAX and neutralization grid")
    robustness.set_defaults(func=cmd_robustness)
    cost_stress = sub.add_parser("cost-stress", help="Run predeclared transaction-cost grid")
    cost_stress.set_defaults(func=cmd_cost_stress)
    validate = sub.add_parser("validate-hist", help="Historical S&P500 validation package")
    validate.set_defaults(func=cmd_validate_hist)
    pit_report = sub.add_parser("pit-report", help="Alias for validate-hist report generation")
    pit_report.set_defaults(func=cmd_pit_report)
    purchase = sub.add_parser(
        "purchase-gate",
        help="FF3/subperiod/leg analysis for Sharadar purchase decision (no retuning)",
    )
    purchase.set_defaults(func=cmd_purchase_gate)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
