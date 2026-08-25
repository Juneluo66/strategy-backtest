"""CLI: audit-data, fetch, backtest, compare, final-audit, robustness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .analytics import bootstrap_sharpe, performance_report, window_reports
from .artifacts import new_run_directory
from .backtest import run_cross_sectional_backtest
from .config import load_config
from .data.prices import (
    common_interval,
    fetch_etf_prices,
    link_or_copy_equity_cache,
    load_adj_panels,
    sgov_inception,
)
from .data.universe import (
    assess_capabilities,
    build_eligible_mask,
    try_load_provider,
    write_data_audit_report,
)
from .etf_adapter import (
    buy_and_hold,
    outer_blend,
    simple_dual_momentum,
    sixty_forty,
    trend_vti_sgov,
    verify_frozen_hash,
)
from .portfolios import build_portfolios
from .reporting import write_final_audit, write_strategy_report
from .status import EARNINGS_SURPRISE_BLOCKED, PEAD_PROXY, PhaseStop, research_status
from .strategies import build_momentum_target, build_multifactor_target


def cmd_audit_data(_: argparse.Namespace) -> int:
    config = load_config()
    link_or_copy_equity_cache(config.cache_dir)
    fetch_etf_prices(config)
    report = assess_capabilities(config)
    path = write_data_audit_report(config, report)
    print(json.dumps({"report": str(path), "grades": report.a_b_c_grades(), **research_status()}, indent=2))
    if report.equity_price_start is None:
        raise PhaseStop("no equity price cache — STOP per H6 Phase 1")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    config = load_config()
    link = link_or_copy_equity_cache(config.cache_dir)
    etf = fetch_etf_prices(config, refresh=args.refresh)
    print(json.dumps({"equity_link": link, "etf": etf}, indent=2))
    return 0 if not etf.get("failures") else 2


def _load_equity_panels(config, limit: int | None = None):
    provider = try_load_provider(config)
    if provider is None:
        raise PhaseStop("membership provider missing — run fetch/link first")
    symbols = provider.all_symbols()
    equity_dir = config.cache_dir / "equity"
    available = []
    for symbol in symbols:
        safe = symbol.replace("-", "_")
        if (equity_dir / f"{safe}.parquet").exists() or (config.cache_dir / f"{safe}.parquet").exists():
            available.append(symbol)
    if limit:
        available = available[:limit]
    if not available:
        raise PhaseStop("no equity prices available")
    opens, closes, volumes = load_adj_panels(config.cache_dir, available, subdir="equity")
    # Drop columns that are all-NA
    opens = opens.dropna(axis=1, how="all")
    closes = closes[opens.columns]
    volumes = volumes.reindex(columns=opens.columns)
    return opens, closes, volumes, provider


def cmd_backtest(args: argparse.Namespace) -> int:
    config = load_config(config_name=Path(args.config).name if args.config else "frozen.yaml")
    if args.config:
        config = load_config(config_name=Path(args.config).name)
    opens, closes, volumes, provider = _load_equity_panels(config, limit=args.limit)
    returns = closes.pct_change(fill_method=None)
    min_price = float(config.raw["universe"]["min_price"])
    min_adv = float(config.raw["universe"]["min_adv_usd"])
    run_dir = new_run_directory(config, f"backtest_{args.strategy}")

    fundamentals_ok = False  # free path: SEC facts not loaded => A/B1-B3 blocked

    results = {}
    if args.strategy in {"B0", "momentum", "all"}:
        for variant in (["B0"] if args.strategy == "B0" else ["B0", "B1", "B2", "B3"]):

            def make_fn(v=variant):
                def _fn(date, previous):
                    members = provider.symbols_on(date)
                    eligible = build_eligible_mask(
                        date, closes, volumes, members, min_price=min_price, min_adv_usd=min_adv
                    )
                    target = build_momentum_target(
                        closes,
                        date,
                        eligible,
                        previous,
                        variant=v,
                        n_holdings=int(config.raw["momentum"]["n_holdings"]),
                        entry_pct=float(config.raw["momentum"]["buffer_entry_pct"]),
                        exit_pct=float(config.raw["momentum"]["buffer_exit_pct"]),
                        quality_ok=fundamentals_ok,
                        returns_for_vol=returns,
                    )
                    return target.weights, target.audit, target.status

                return _fn

            out = run_cross_sectional_backtest(
                opens,
                closes,
                volumes,
                target_fn=make_fn(),
                membership_on=provider.symbols_on,
                cost_scenario=args.cost,
            )
            results[variant] = out
            out["equity"].to_csv(run_dir / f"equity_{variant}.csv")
            out["targets"].to_csv(run_dir / f"targets_{variant}.csv", index=False)
            out["trades"].to_csv(run_dir / f"trades_{variant}.csv", index=False)
            out["exits"].to_csv(run_dir / f"exits_{variant}.csv", index=False)

    if args.strategy in {"A", "multifactor", "all"}:

        def a_fn(date, previous):
            members = provider.symbols_on(date)
            eligible = build_eligible_mask(
                date, closes, volumes, members, min_price=min_price, min_adv_usd=min_adv
            )
            target = build_multifactor_target(
                closes,
                date,
                eligible,
                previous,
                fundamentals_ok=fundamentals_ok,
                n_holdings=int(config.raw["multifactor"]["n_holdings"]),
            )
            return target.weights, target.audit, target.status

        out = run_cross_sectional_backtest(
            opens,
            closes,
            volumes,
            target_fn=a_fn,
            membership_on=provider.symbols_on,
            cost_scenario=args.cost,
        )
        results["A"] = out
        out["equity"].to_csv(run_dir / "equity_A.csv")

    # PEAD formal blocked
    pead_status = {
        "formal": EARNINGS_SURPRISE_BLOCKED,
        "proxy_label": PEAD_PROXY,
        "may_enter_portfolio": False,
    }
    (run_dir / "pead_status.json").write_text(json.dumps(pead_status, indent=2), encoding="utf-8")

    # Benchmark VTI
    _, etf_c, _ = load_adj_panels(config.cache_dir, ["VTI", "SPY"], subdir="etf")
    bench = etf_c["VTI"]
    summary = {}
    windows = config.raw["research_windows"]
    for name, out in results.items():
        if out["equity"].empty:
            summary[name] = {"status": "EMPTY_OR_BLOCKED"}
            continue
        metrics = performance_report(out["equity"], out["trades"], bench)
        metrics["bootstrap_sharpe"] = bootstrap_sharpe(
            out["equity"]["net_return"], seed=int(config.raw["random_seed"])
        )
        summary[name] = {
            "status": "OK" if name == "B0" else ("BLOCKED" if name != "B0" and not fundamentals_ok else "OK"),
            "cost_scenario": args.cost,
            "metrics": metrics,
            "windows": window_reports(out["equity"], out["trades"], bench, windows),
        }
    summary["_meta"] = {
        "cost_scenario": args.cost,
        "return_basis": config.return_basis,
        "symbol_limit": args.limit,
        "fundamentals_ok": fundamentals_ok,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(run_dir)
    return 0


def cmd_compare(_: argparse.Namespace) -> int:
    config = load_config()
    run_dir = new_run_directory(config, "compare")
    hash_check = verify_frozen_hash(config.raw["etf_controls"]["expected_config_hash_prefix"])
    if not hash_check["ok"]:
        # Soft warning: still continue with note — STOP only if we claim freeze match falsely
        (run_dir / "hash_check.json").write_text(json.dumps(hash_check, indent=2), encoding="utf-8")
        # Recompute against dual_momentum package if importable
    else:
        (run_dir / "hash_check.json").write_text(json.dumps(hash_check, indent=2), encoding="utf-8")

    symbols = list(config.universe["etf_fetch_symbols"])
    _, closes, _ = load_adj_panels(config.cache_dir, symbols, subdir="etf")
    sgov_start = sgov_inception(closes)
    vti_r = buy_and_hold(closes["VTI"])
    spy_r = buy_and_hold(closes["SPY"])
    sf = sixty_forty(closes["SPY"], closes["IEF"])
    trend = trend_vti_sgov(closes)
    # Dual mom on VTI/VXUS + cash
    opens, _, _ = load_adj_panels(config.cache_dir, symbols, subdir="etf")
    dual = simple_dual_momentum(
        opens,
        closes,
        ["VTI", "VXUS"],
        category_map={"VTI": "us", "VXUS": "intl"},
        require_trend_consistency=True,
    )
    # Try load B0 equity if present from latest run
    equity_r = None
    runs = sorted((config.reports_dir / "runs").glob("*_backtest_*"))
    for run in reversed(runs):
        path = run / "equity_B0.csv"
        if path.exists():
            eq = pd.read_csv(path, parse_dates=["date"]).set_index("date")
            equity_r = eq["net_return"]
            break

    # Frozen D+C: prefer dual_momentum attribution if we can import runner
    dc_r = dual["net_return"]
    try:
        from dual_momentum_etf.backtest import run_variant
        from dual_momentum_etf.config import load_config as load_dm
        from dual_momentum_etf.data import load_ohlc

        dm = load_dm()
        o, c = load_ohlc(dm)
        dc_out = run_variant(o, c, dm, "attribution_DC")
        dc_r = dc_out["equity"]["net_return"]
    except Exception as exc:  # noqa: BLE001 — adapter must not crash compare
        (run_dir / "dc_adapter_warning.txt").write_text(str(exc), encoding="utf-8")

    series_map = {
        "vti": vti_r,
        "spy": spy_r,
        "sixty_forty": sf,
        "trend": trend,
        "dual_vti_vxus": dual["net_return"],
        "dc": dc_r,
    }
    if equity_r is not None:
        series_map["b0"] = equity_r
    start, end = common_interval(series_map)
    clipped = {k: v.loc[start:end] for k, v in series_map.items()}

    rows = []
    for name, series in clipped.items():
        equity = pd.DataFrame(
            {
                "gross_return": series,
                "net_return": series,
                "n_holdings": np.nan,
            },
            index=series.index,
        )
        trades = pd.DataFrame()
        metrics = performance_report(equity, trades, closes["VTI"])
        rows.append({"name": name, **metrics})
    pd.DataFrame(rows).to_csv(run_dir / "etf_comparison.csv", index=False)

    frozen_blend = outer_blend(clipped["spy"], clipped["dc"], 0.8, 0.2)
    vti_blend = outer_blend(clipped["vti"], clipped["dc"], 0.8, 0.2)
    pd.DataFrame({"frozen_80_20_spy_dc": frozen_blend, "exp_80_20_vti_dc": vti_blend}).to_csv(
        run_dir / "sleeves.csv"
    )

    # Portfolios
    grade_b0 = "RESEARCH ONLY"
    ports = build_portfolios(
        vti=clipped["vti"],
        spy=clipped["spy"],
        dc=clipped["dc"],
        equity=clipped.get("b0"),
        equity_grade=grade_b0,
        equity_is_pead_proxy=False,
        qual=buy_and_hold(closes["QUAL"]).loc[start:end] if "QUAL" in closes.columns else None,
    )
    port_rows = []
    for name, series in ports.items():
        if series.empty or series.name and str(series.name).startswith("SKIPPED"):
            port_rows.append({"portfolio": name, "status": str(series.name) if series.name else "EMPTY"})
            continue
        eq = pd.DataFrame({"gross_return": series, "net_return": series}, index=series.index)
        port_rows.append({"portfolio": name, "status": "OK", **performance_report(eq, pd.DataFrame(), closes["VTI"])})
    pd.DataFrame(port_rows).to_csv(run_dir / "portfolios.csv", index=False)

    # Markdown reports
    etf_md = config.reports_dir / "us_equity_etf_comparison.md"
    etf_md.write_text(
        "\n".join(
            [
                "# US Equity ETF Comparison",
                "",
                f"- Common interval (H4): `{start.date()}` → `{end.date()}`",
                f"- SGOV inception: `{sgov_start.date() if sgov_start is not None else 'n/a'}`",
                f"- Frozen D+C hash check: `{json.dumps(hash_check)}`",
                f"- return_basis: `{config.return_basis}`",
                "",
                "See `reports/runs/.../etf_comparison.csv` and `sleeves.csv`.",
                "",
                "Frozen paper candidate remains **80% SPY + 20% D+C** (not VTI sleeve).",
                "",
            ]
        ),
        encoding="utf-8",
    )
    port_md = config.reports_dir / "us_equity_portfolio_comparison.md"
    port_md.write_text(
        "\n".join(
            [
                "# Portfolio Comparison P0–P5",
                "",
                "- P2/P3/P5 skipped unless equity grade is PASS/CONDITIONAL PASS.",
                f"- B0 grade used: `{grade_b0}` → P2/P3 skipped by gate.",
                "- P1 is the frozen 80/20 SPY/D+C control.",
                "- EXP_80_20_VTI_DC is experimental only.",
                "",
                "```json",
                json.dumps(port_rows, indent=2, default=str),
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(run_dir)
    return 0


def cmd_robustness(_: argparse.Namespace) -> int:
    config = load_config()
    run_dir = new_run_directory(config, "robustness")
    # Predeclared sensitivity grid — does not pick winners
    opens, closes, volumes, provider = _load_equity_panels(config, limit=80)
    returns = closes.pct_change(fill_method=None)
    rows = []
    for min_price in config.raw["universe"]["min_price_sensitivity"]:
        def fn(date, previous, mp=min_price):
            members = provider.symbols_on(date)
            eligible = build_eligible_mask(
                date, closes, volumes, members, min_price=float(mp), min_adv_usd=5_000_000
            )
            target = build_momentum_target(
                closes, date, eligible, previous, variant="B0", returns_for_vol=returns
            )
            return target.weights, target.audit, target.status

        out = run_cross_sectional_backtest(
            opens, closes, volumes, target_fn=fn, membership_on=provider.symbols_on
        )
        if out["equity"].empty:
            rows.append({"min_price": min_price, "status": "EMPTY"})
            continue
        _, etf_c, _ = load_adj_panels(config.cache_dir, ["VTI"], subdir="etf")
        metrics = performance_report(out["equity"], out["trades"], etf_c["VTI"])
        rows.append({"min_price": min_price, "status": "OK", "net_sharpe": metrics.get("net_sharpe"), "net_cagr": metrics.get("net_cagr"), "net_max_drawdown": metrics.get("net_max_drawdown")})
    # Cap percentile sensitivity blocked
    rows.append(
        {
            "min_price": "cap_percentile_70_80_90",
            "status": "BLOCKED_BY_PIT_MARKET_CAP",
            "net_sharpe": None,
            "net_cagr": None,
            "net_max_drawdown": None,
        }
    )
    pd.DataFrame(rows).to_csv(run_dir / "robustness_grid.csv", index=False)
    print(run_dir)
    return 0


def cmd_final_audit(_: argparse.Namespace) -> int:
    config = load_config()
    # Ensure data audit exists
    report = assess_capabilities(config)
    write_data_audit_report(config, report)
    grades_impl = report.a_b_c_grades()

    # Load latest B0 metrics if any
    b0_metrics = {}
    runs = sorted((config.reports_dir / "runs").glob("*_backtest_*"))
    for run in reversed(runs):
        summary = run / "summary.json"
        if summary.exists():
            payload = json.loads(summary.read_text(encoding="utf-8"))
            b0_metrics = payload.get("B0", {})
            break

    grade_a = "FAIL" if grades_impl["A_multifactor"] == "BLOCKED" else "RESEARCH ONLY"
    grade_b0 = "RESEARCH ONLY"
    grade_b_quality = "FAIL" if grades_impl["B1_B3_quality_filter"] == "BLOCKED" else "RESEARCH ONLY"
    grade_c = "FAIL"  # formal PEAD blocked
    grade_c_proxy = "RESEARCH ONLY"
    grade_etf = "PASS"  # frozen D+C already audited in sibling project
    grade_8020 = "PASS"

    # Write strategy reports
    write_strategy_report(
        config.reports_dir / "us_equity_multifactor_report.md",
        title="Strategy A — Quality + Value + Momentum",
        rules=[
            "Frozen weights 30/35/35",
            "Requires filed-based PIT fundamentals (H2)",
            "Month-end signal / next-open execution",
        ],
        data_limits=[
            "SEC Company Facts not loaded on free path → BLOCKED",
            "No PIT market cap; cannot claim US top-80% universe",
        ],
        metrics={},
        windows={},
        grade=grade_a,
        extras=["## Verdict", "", "Evidence insufficient for paper trading. Do not enter P2/P3/P5."],
    )
    write_strategy_report(
        config.reports_dir / "us_equity_momentum_report.md",
        title="Strategy B — Quality-filtered 12-1 Momentum",
        rules=[
            "B0: pure 12-1 momentum (skip 1 month)",
            "B1–B3: require PIT quality filters (blocked without fundamentals)",
            "Buffer 10%/20%; next-open execution; dynamic costs",
        ],
        data_limits=[
            "Universe = HISTORICAL_SP500_APPROX (survivorship reduced not eliminated)",
            "DELISTING_RETURN unavailable; INDEX_EXIT ≠ DELISTING",
            "B1–B3 BLOCKED without PIT quality",
        ],
        metrics=b0_metrics.get("metrics", {}),
        windows=b0_metrics.get("windows", {}),
        grade=grade_b0,
        extras=[
            "## Sub-grades",
            f"- B0: `{grade_b0}`",
            f"- B1–B3: `{grade_b_quality}`",
            "",
            "B0 is research-grade price momentum only — not sufficient for PASS into paper without stronger PIT/delisting evidence.",
        ],
    )
    write_strategy_report(
        config.reports_dir / "us_equity_pead_report.md",
        title="Strategy C — PEAD",
        rules=["Formal SUE requires announce time + pre-announce consensus PIT"],
        data_limits=[
            "No earnings surprise / consensus snapshot in repository",
            "YoY EPS change may only be labeled PEAD_PROXY",
            "Proxy may NOT enter portfolio experiments",
        ],
        metrics={},
        windows={},
        grade=grade_c,
        extras=[
            f"- Formal PEAD: `{grade_c}` / `{EARNINGS_SURPRISE_BLOCKED}`",
            f"- Proxy label: `{PEAD_PROXY}` grade `{grade_c_proxy}`",
        ],
    )

    answers = {
        "1. Best strategy after tradability / no-leakage / costs?": (
            "Among implementations that clear data gates, the frozen ETF sleeve "
            "**80% SPY + 20% D+C** remains the only PASS-level candidate. "
            "B0 momentum is RESEARCH ONLY; A and formal PEAD are FAIL/BLOCKED on free data."
        ),
        "2. Best for individual investor paper trading?": (
            "Frozen **80% SPY + 20% D+C** (already seeded in dual_momentum_etf paper books). "
            "Individual single-stock books are not recommended on current evidence."
        ),
        "3. Can equity strategies improve ETF sleeve return/DD/diversification?": (
            "Not established. P2/P3 were skipped because no equity strategy reached "
            "PASS/CONDITIONAL PASS. B0 likely overlaps equity beta with SPY/VTI."
        ),
        "4. Run equity standalone or combine with ETF?": (
            "Do not combine until an equity sleeve earns CONDITIONAL PASS or better. "
            "Current evidence does not support replacing or diluting the frozen ETF candidate with A/B/C."
        ),
        "5. Enough evidence for paper trading?": (
            "ETF 80/20: yes (sibling final-audit PASS). Equity A/B/C: no — RESEARCH ONLY / FAIL. "
            "Overall equity add-on: stay in research stage."
        ),
    }
    write_final_audit(
        config.reports_dir / "us_equity_final_audit.md",
        grades={
            "A_multifactor": grade_a,
            "B0_momentum": grade_b0,
            "B1_B3_momentum_quality": grade_b_quality,
            "C_formal_pead": grade_c,
            "C_pead_proxy": grade_c_proxy,
            "ETF_D+C": grade_etf,
            "sleeve_80_20_SPY_DC": grade_8020,
        },
        answers=answers,
        primary="80% SPY + 20% attribution_DC (dual_momentum_etf frozen)",
        shadow=["60% SPY + 40% D+C (conservative shadow only)", "B0 12-1 momentum RESEARCH ONLY"],
        limitations=[
            "PIT_VALIDATED=false",
            "DELISTING_RETURN=UNAVAILABLE",
            "No PIT market cap → top-80% universe BLOCKED",
            "No analyst consensus → formal PEAD BLOCKED",
            "SEC filed facts not integrated for A/B quality in this run",
            "Survivorship bias reduced not eliminated",
        ],
        commands=[
            "cd /home/ec2-user/strategy-backtest/us_equity_strategy_research",
            "python3 -m pip install -e '.[dev]'",
            "us-equity-research audit-data",
            "us-equity-research fetch",
            "us-equity-research backtest --strategy all --limit 100",
            "us-equity-research robustness",
            "us-equity-research compare",
            "us-equity-research final-audit",
        ],
    )
    status_path = config.reports_dir / "PROJECT_STATUS.md"
    status_path.write_text(
        "\n".join(
            [
                "# US Equity Strategy Research — Project Status",
                "",
                f"- Updated: `{pd.Timestamp.utcnow().isoformat()}`",
                f"- return_basis: `{config.return_basis}`",
                "- Primary paper candidate: **80% SPY + 20% D+C** (sibling freeze)",
                "- Equity A/B/C: **not** cleared for paper",
                "- See `us_equity_final_audit.md`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(config.reports_dir / "us_equity_final_audit.md")
    return 0


def cmd_etf_trend_sleeves(_: argparse.Namespace) -> int:
    from .etf_trend_sleeves import run_etf_trend_experiments

    path = run_etf_trend_experiments()
    print(path)
    return 0


def cmd_spy_qqq_protect_audit(_: argparse.Namespace) -> int:
    from .spy_qqq_protect_audit import run_spy_qqq_protect_audit

    path = run_spy_qqq_protect_audit()
    print(path)
    return 0


def cmd_half_protect_relative_audit(_: argparse.Namespace) -> int:
    from .half_protect_relative_audit import run_half_protect_relative_audit

    path = run_half_protect_relative_audit()
    print(path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="us-equity-research")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("audit-data", help="Phase 1 data capability audit")
    p.set_defaults(func=cmd_audit_data)

    p = sub.add_parser("fetch", help="Link equity cache and fetch ETF bars")
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("backtest", help="Run A/B strategies (C gated)")
    p.add_argument("--config", default="configs/frozen.yaml")
    p.add_argument("--strategy", default="all", choices=["all", "A", "multifactor", "B0", "momentum"])
    p.add_argument("--cost", default="baseline", choices=["optimistic", "baseline", "stress"])
    p.add_argument("--limit", type=int, default=None, help="Limit symbols for smoke runs")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("robustness", help="Predeclared sensitivity grid")
    p.set_defaults(func=cmd_robustness)

    p = sub.add_parser("compare", help="ETF + portfolio comparison")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("final-audit", help="Write final grades and PROJECT_STATUS")
    p.set_defaults(func=cmd_final_audit)

    p = sub.add_parser(
        "etf-trend-sleeves",
        help="Run frozen ETF rotation + SPY/QQQ protect + F3 vs 80/20 D+C",
    )
    p.set_defaults(func=cmd_etf_trend_sleeves)

    p = sub.add_parser(
        "spy-qqq-protect-audit",
        help="Pre-registered full/half/joint_half protect audit vs frozen 80/20 & 60/40",
    )
    p.set_defaults(func=cmd_spy_qqq_protect_audit)

    p = sub.add_parser(
        "half-protect-relative-audit",
        help="Metric C relative audit of frozen half_protect vs 80/20, 60/40, SPY",
    )
    p.set_defaults(func=cmd_half_protect_relative_audit)

    args = parser.parse_args()
    try:
        return args.func(args)
    except PhaseStop as exc:
        print(json.dumps({"phase_stop": str(exc)}, indent=2))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
