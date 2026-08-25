"""CLI: fetch → audit → run → ablation → cost-stress → report → reproduce."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Optional

from .artifacts import new_run_directory
from .attribution import run_attribution, write_attribution_report
from .backtest import run_variant
from .config import load_config
from .confirmation import run_confirmation, write_confirmation_report
from .sleeve_evaluation import run_sleeve_evaluation, write_sleeve_report
from .sleeve_final_audit import run_final_sleeve_audit, write_final_audit_md
from .paper_runner import run_paper_books
from .data import audit_cache, fetch_prices, load_ohlc
from .reporting import compute_and_save, write_summary_md


def _parse_variants(raw: Optional[str], default: list[str]) -> list[str]:
    if not raw:
        return default
    return [part.strip() for part in raw.split(",") if part.strip()]


def cmd_fetch(args: argparse.Namespace) -> int:
    config = load_config()
    manifest = fetch_prices(config, refresh=bool(args.refresh))
    print(json.dumps(manifest, indent=2))
    return 0 if not manifest["failures"] else 2


def cmd_audit(_: argparse.Namespace) -> int:
    config = load_config()
    report = audit_cache(config)
    directory = new_run_directory(config, "audit")
    (directory / "data_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"run_dir": str(directory), **{k: report[k] for k in ("status",)}}, indent=2))
    return 0 if report.get("status") in {"OK", "PARTIAL"} else 1


def _run_variants(variant_names: list[str], command: str, one_way_bps: Optional[float] = None) -> Path:
    config = load_config()
    opens, closes = load_ohlc(config)
    benchmark = closes[config.raw["benchmark"]]
    directory = new_run_directory(config, command)
    metrics_by_variant = {}
    for name in variant_names:
        result = run_variant(opens, closes, config, name, one_way_bps=one_way_bps)
        metrics = compute_and_save(directory, result, benchmark, config.raw["research_windows"])
        metrics_by_variant[name] = metrics
        print(json.dumps({"variant": name, "net_sharpe": metrics.get("net_sharpe"), "net_cagr": metrics.get("net_cagr")}))
    notes = [
        f"one_way_bps={one_way_bps if one_way_bps is not None else config.raw['costs']['one_way_bps']}",
        "Signal at month-end close; execution at next session open.",
        "Cash sleeve: SGOV with BIL proxy before SGOV availability.",
        "No leverage, no shorting.",
    ]
    write_summary_md(directory / "summary.md", variant_metrics=metrics_by_variant, notes=notes)
    (directory / "variant_metrics.json").write_text(
        json.dumps(metrics_by_variant, indent=2, default=str), encoding="utf-8"
    )
    print(directory)
    return directory


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config()
    variants = _parse_variants(args.variants, ["baseline_6", "own_v1"])
    for name in variants:
        config.variant(name)  # validate early
    _run_variants(variants, "run")
    return 0


def cmd_ablation(_: argparse.Namespace) -> int:
    variants = ["baseline_6", "A_vol_adj", "B_regime_size", "C_trend_consistency", "D_category_only", "own_v1"]
    _run_variants(variants, "ablation")
    return 0


def cmd_cost_stress(_: argparse.Namespace) -> int:
    config = load_config()
    opens, closes = load_ohlc(config)
    benchmark = closes[config.raw["benchmark"]]
    directory = new_run_directory(config, "cost_stress")
    rows = []
    for bps in config.raw["costs"]["stress_one_way_bps"]:
        for name in ["baseline_6", "own_v1"]:
            result = run_variant(opens, closes, config, name, one_way_bps=float(bps))
            metrics = compute_and_save(directory, result, benchmark, config.raw["research_windows"])
            # Avoid clobbering same variant filenames across bps: rename copies.
            for suffix in ["equity", "targets", "trades", "metrics"]:
                src = directory / f"{name}_{suffix}.csv" if suffix != "metrics" else directory / f"{name}_metrics.json"
                if suffix == "metrics":
                    dst = directory / f"{name}_bps{bps}_{suffix}.json"
                else:
                    dst = directory / f"{name}_bps{bps}_{suffix}.csv"
                if src.exists():
                    shutil.move(str(src), str(dst))
            # monthly scores / audit shared — keep last copy under bps name if present
            for extra in ["monthly_scores", "audit", "cash_switches"]:
                src = directory / f"{name}_{extra}.csv"
                if src.exists():
                    shutil.move(str(src), str(directory / f"{name}_bps{bps}_{extra}.csv"))
            rows.append(
                {
                    "variant": name,
                    "one_way_bps": bps,
                    "net_cagr": metrics.get("net_cagr"),
                    "net_sharpe": metrics.get("net_sharpe"),
                    "net_max_drawdown": metrics.get("net_max_drawdown"),
                    "annualized_turnover": metrics.get("annualized_turnover"),
                }
            )
    import pandas as pd

    frame = pd.DataFrame(rows)
    frame.to_csv(directory / "cost_stress.csv", index=False)
    write_summary_md(
        directory / "summary.md",
        variant_metrics={
            f"{r['variant']}_bps{r['one_way_bps']}": {
                "net_cagr": r["net_cagr"],
                "net_volatility": float("nan"),
                "net_sharpe": r["net_sharpe"],
                "net_max_drawdown": r["net_max_drawdown"],
                "annualized_turnover": r["annualized_turnover"],
                "qqq_held_pct": float("nan"),
                "spy_qqq_cohold_pct": float("nan"),
                "benchmark_sharpe": float("nan"),
            }
            for r in rows
        },
        notes=["Cost stress grid over frozen one-way bps assumptions."],
    )
    print(directory)
    return 0


def cmd_sleeve(_: argparse.Namespace) -> int:
    """Evaluate D+C as a pre-declared SPY defensive sleeve (no weight search)."""
    config = load_config()
    opens, closes = load_ohlc(config)
    directory = new_run_directory(config, "sleeve")
    study = run_sleeve_evaluation(config, opens, closes)
    path = write_sleeve_report(
        directory,
        study,
        promote_to=config.reports_dir / "dc_sleeve_evaluation.md",
    )
    print(json.dumps(study["verdict"], indent=2, default=str))
    print(path)
    print(config.reports_dir / "dc_sleeve_evaluation.md")
    return 0


def cmd_final_audit(args: argparse.Namespace) -> int:
    """PIT-safe outer blend audit + simple defenses; optionally seed IBKR paper books."""
    config = load_config()
    opens, closes = load_ohlc(config)
    directory = new_run_directory(config, "final_audit")
    study = run_final_sleeve_audit(config, opens, closes)
    path = write_final_audit_md(
        directory,
        study,
        promote_to=config.reports_dir / "dc_sleeve_final_audit.md",
    )
    summary = {
        "audit_pass": study["audit_pass"],
        "default_candidate": study["default_candidate"],
        "precision_cagr_gap_pp": study["precision"]["cagr_gap_full"] * 100,
        "judgment": study["simple_benchmark_comparison"]["judgment"],
    }
    print(json.dumps(summary, indent=2, default=str))
    print(path)
    print(config.reports_dir / "dc_sleeve_final_audit.md")

    if study["audit_pass"] and not getattr(args, "skip_paper", False):
        try:
            paper_dir = new_run_directory(config, "paper")
            paper_summary = run_paper_books(
                config,
                opens,
                closes,
                study["dc_result"]["targets"],
                paper_dir,
            )
            (config.reports_dir / "paper_books_summary.json").write_text(
                json.dumps(paper_summary, indent=2, default=str), encoding="utf-8"
            )
            print(json.dumps({"paper_dir": str(paper_dir), "books": list(paper_summary["books"])}, indent=2))
            _write_project_status(config, study, paper_summary)
        except Exception as exc:  # noqa: BLE001 — surface paper failure without losing audit
            print(json.dumps({"paper_error": str(exc)}, indent=2))
            _write_project_status(config, study, None)
            return 3
    else:
        _write_project_status(config, study, None)
    return 0 if study["audit_pass"] else 2


def cmd_paper(_: argparse.Namespace) -> int:
    """Run IBKR-constraint paper books (requires frozen D+C targets)."""
    config = load_config()
    opens, closes = load_ohlc(config)
    dc_name = config.raw.get("confirmation", {}).get("frozen_variant", "attribution_DC")
    horizons = tuple(config.raw.get("confirmation", {}).get("frozen_trend_horizons", [3, 6, 12]))
    dc = run_variant(opens, closes, config, dc_name, trend_horizons=horizons)
    directory = new_run_directory(config, "paper")
    summary = run_paper_books(config, opens, closes, dc["targets"], directory)
    (config.reports_dir / "paper_books_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({"paper_dir": str(directory), "books": summary["books"]}, indent=2, default=str))
    return 0


def _write_project_status(config, study, paper_summary) -> None:
    from datetime import datetime, timezone

    lines = [
        "# Dual Momentum ETF — Project Status",
        "",
        f"- Updated: `{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}`",
        f"- config_hash: `{study['config_hash']}`",
        "",
        "## Frozen decisions",
        "",
        "- **D+C rules frozen**: `attribution_DC` — score 0.6·R5M+0.4·R12M, price>10m SMA,",
        "  trend consistency **3/6/12 all > 0**, category max 1, top-2 equal weight, no hysteresis, no regime B.",
        "- **Do not** retune 3/6/12, category constraints, or search new sleeve weights.",
        "- **Default paper candidate**: **80% SPY + 20% D+C**",
        "- **Conservative shadow only**: 60% SPY + 40% D+C (not an optimized alternative).",
        "",
        "## Final audit",
        "",
        f"- Gate: **{'PASS' if study['audit_pass'] else 'FAIL'}**",
        f"- Report: `reports/dc_sleeve_final_audit.md`",
        f"- Sample: `{study['common_start']}` → `{study['sample_end']}`",
        f"- 80/20 vs SPY CAGR gap (full precision): `{study['precision']['cagr_gap_full']*100:.6f}pp`",
        f"- 20% D+C vs simple 20% defenses (MaxDD better than all): "
        f"**{study['simple_benchmark_comparison']['judgment']['dc_sleeve_better_maxdd_than_simple_20pct']}**",
        f"- Verdict: {study['simple_benchmark_comparison']['judgment'].get('verdict', '')}",
        "",
        "## Paper trading (IBKR constraints, no live orders)",
        "",
    ]
    if paper_summary:
        lines.append("- Status: **seeded** (research simulator)")
        lines.append("- Config: `configs/paper_trading.yaml`")
        lines.append("- Books:")
        for bid, meta in paper_summary["books"].items():
            lines.append(
                f"  - `{bid}` ({meta.get('role')}): final_nav≈{meta.get('final_nav')}, "
                f"log_events={meta.get('n_log_events')}"
            )
        lines.append("- Artifacts: latest `reports/runs/*_paper_*` + `reports/paper_books_summary.json`")
    else:
        lines.append("- Status: **not seeded** (audit failed or `--skip-paper`)")
    lines.extend(
        [
            "",
            "## Parallel books maintained",
            "",
            "1. `candidate_80_20_dc` — formal default",
            "2. `opp_cost_100_spy` — opportunity cost",
            "3. `shadow_60_40_dc` — conservative shadow",
            "4. `traditional_60_40_ief` — traditional 60/40",
            "",
        ]
    )
    path = config.reports_dir / "PROJECT_STATUS.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(path)


def cmd_confirm(_: argparse.Namespace) -> int:
    """Final D+C confirmation validation (frozen rules, no combo search)."""
    config = load_config()
    opens, closes = load_ohlc(config)
    directory = new_run_directory(config, "confirm")
    study = run_confirmation(config, opens, closes)
    path = write_confirmation_report(
        directory,
        study,
        promote_to=config.reports_dir / "dc_confirmation.md",
    )
    print(json.dumps({"PASS": study["gates"]["PASS"], **study["gates"]["notes"]}, indent=2, default=str))
    print(path)
    print(config.reports_dir / "dc_confirmation.md")
    return 0 if study["gates"]["PASS"] else 2


def cmd_attribution(_: argparse.Namespace) -> int:
    """Frozen interaction attribution vs external benchmarks (no B)."""
    config = load_config()
    opens, closes = load_ohlc(config)
    directory = new_run_directory(config, "attribution")
    study = run_attribution(config, opens, closes)
    path = write_attribution_report(
        directory,
        study,
        promote_to=config.reports_dir / "interaction_attribution.md",
    )
    # Compact console table
    for name in study["experiments"]:
        s = study["bundles"][name]["summary"]
        print(
            json.dumps(
                {
                    "variant": name,
                    "net_cagr": s["net_cagr"],
                    "net_sharpe": s["net_sharpe"],
                    "net_max_drawdown": s["net_max_drawdown"],
                }
            )
        )
    for name in study["benchmarks"]:
        s = study["bundles"][name]["summary"]
        print(
            json.dumps(
                {
                    "benchmark": name,
                    "net_cagr": s["net_cagr"],
                    "net_sharpe": s["net_sharpe"],
                    "net_max_drawdown": s["net_max_drawdown"],
                }
            )
        )
    print(path)
    print(config.reports_dir / "interaction_attribution.md")
    return 0


def cmd_report(_: argparse.Namespace) -> int:
    """Promote latest run/ablation metrics into reports/dual_momentum_summary.md."""
    config = load_config()
    runs = sorted((config.reports_dir / "runs").glob("*"), key=lambda p: p.name)
    if not runs:
        print("no runs found; execute run/ablation first")
        return 1
    # Prefer latest ablation, else latest run.
    chosen = None
    for path in reversed(runs):
        if "_ablation_" in path.name or path.name.endswith("ablation") or "ablation" in path.name:
            if (path / "variant_metrics.json").exists():
                chosen = path
                break
    if chosen is None:
        for path in reversed(runs):
            if (path / "variant_metrics.json").exists():
                chosen = path
                break
    if chosen is None:
        print("no variant_metrics.json found")
        return 1
    metrics = json.loads((chosen / "variant_metrics.json").read_text(encoding="utf-8"))
    out = config.reports_dir / "dual_momentum_summary.md"
    write_summary_md(
        out,
        variant_metrics=metrics,
        notes=[
            f"Source run: `{chosen.name}`",
            "Primary conclusion variant: own_v1 (category + vol-adjust + MA filter + hysteresis).",
            "baseline_6 is the public dual-momentum reference.",
        ],
    )
    shutil.copy2(chosen / "variant_metrics.json", config.reports_dir / "dual_momentum_metrics.json")
    print(out)
    return 0


def cmd_reproduce(_: argparse.Namespace) -> int:
    class NS:
        refresh = False
        variants = "baseline_6,own_v1"

    rc = cmd_fetch(NS())  # type: ignore[arg-type]
    if rc not in (0, 2):
        return rc
    cmd_audit(NS())  # type: ignore[arg-type]
    cmd_run(NS())  # type: ignore[arg-type]
    cmd_ablation(NS())  # type: ignore[arg-type]
    cmd_cost_stress(NS())  # type: ignore[arg-type]
    return cmd_report(NS())  # type: ignore[arg-type]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dual-momentum-etf")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="Download Yahoo OHLCV into data/cache")
    fetch.add_argument("--refresh", action="store_true")
    fetch.set_defaults(func=cmd_fetch)

    audit = sub.add_parser("audit", help="Audit cached price coverage")
    audit.set_defaults(func=cmd_audit)

    run = sub.add_parser("run", help="Run named variants")
    run.add_argument("--variants", default="baseline_6,own_v1")
    run.set_defaults(func=cmd_run)

    ablation = sub.add_parser("ablation", help="Run A/B/C/D structural ablations plus baselines")
    ablation.set_defaults(func=cmd_ablation)

    cost = sub.add_parser("cost-stress", help="Stress one-way cost assumptions")
    cost.set_defaults(func=cmd_cost_stress)

    sleeve = sub.add_parser(
        "sleeve",
        help="Evaluate D+C as pre-declared SPY defensive sleeve (no weight search)",
    )
    sleeve.set_defaults(func=cmd_sleeve)

    final_audit = sub.add_parser(
        "final-audit",
        help="PIT outer-blend final audit + optional IBKR paper seed (D+C frozen)",
    )
    final_audit.add_argument(
        "--skip-paper",
        action="store_true",
        help="Write audit only; do not seed paper books",
    )
    final_audit.set_defaults(func=cmd_final_audit)

    paper = sub.add_parser(
        "paper",
        help="Run IBKR-constraint paper books for 80/20, 100% SPY, 60/40 DC, 60/40 IEF",
    )
    paper.set_defaults(func=cmd_paper)

    confirm = sub.add_parser(
        "confirm",
        help="Final D+C confirmation (OOS/rolling/crisis/cost/neighborhood/PIT); no combo search",
    )
    confirm.set_defaults(func=cmd_confirm)

    attribution = sub.add_parser(
        "attribution",
        help="Interaction attribution grid (A/C/D/hyst) vs external benchmarks; excludes B",
    )
    attribution.set_defaults(func=cmd_attribution)

    report = sub.add_parser("report", help="Write reports/dual_momentum_summary.md")
    report.set_defaults(func=cmd_report)

    reproduce = sub.add_parser("reproduce", help="fetch→audit→run→ablation→cost-stress→report")
    reproduce.set_defaults(func=cmd_reproduce)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
