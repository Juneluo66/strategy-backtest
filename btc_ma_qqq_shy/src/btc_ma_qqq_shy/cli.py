"""CLI: fetch | backtest | full-audit | diagnostics."""
from __future__ import annotations

import argparse
import json
import sys

from .backtest import run_backtest
from .config import ProjectConfig
from .data import fetch_prices
from .diagnostics import run_diagnostics
from .diagnostics_report import write_diagnostics_report
from .report import write_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="btc-ma-qqq")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="Download Yahoo prices")
    p_fetch.add_argument("--refresh", action="store_true")

    sub.add_parser("backtest", help="Run audit backtest and write report")
    sub.add_parser("full-audit", help="Fetch (if needed) + backtest")
    sub.add_parser(
        "diagnostics",
        help="Return-vs-risk timing battery (conditionals, HAC, placebos, grid, bootstrap)",
    )
    sub.add_parser(
        "reconcile",
        help="QC 0.838 vs local 1.22 implementation reconciliation (weekly signals)",
    )
    sub.add_parser(
        "costs",
        help="Cost sweep (1/2/5/10 bps) + next-open + Sunday BTC timestamp look-ahead audit",
    )
    sub.add_parser(
        "mechanism",
        help="Macro correlates + VIF + partial R² + rolling / incremental OOS R²",
    )
    p_oos = sub.add_parser("oos-append", help="Append new frozen OOS weeks (never rewrite history)")
    p_oos.add_argument("--dry-run", action="store_true")
    sub.add_parser("oos-status", help="Show frozen OOS ledger status")
    sub.add_parser("risk-predict", help="Forward risk prediction: RV/drawdown logit vs VIX/RV/trend")
    sub.add_parser("risk-matched", help="Compare BTC timing vs occupancy/vol/beta-matched static QQQ/SHY")
    sub.add_parser(
        "timing-attribution",
        help="Active return A/B vs vol-matched static + frozen QQQ 200DMA benchmark",
    )
    sub.add_parser(
        "traditional-combo",
        help="Frozen QQQ trend + VIX comparator vs BTC (discovery audit)",
    )
    sub.add_parser(
        "oos-propositions",
        help="Track 3 OOS propositions: risk-on spread, risk-off tails, active vs static",
    )

    args = parser.parse_args(argv)
    config = ProjectConfig()

    if args.cmd == "fetch":
        result = fetch_prices(config, refresh=args.refresh)
        print(json.dumps(result, indent=2))
        return 0 if not result["failures"] else 1

    if args.cmd in ("backtest", "full-audit"):
        if args.cmd == "full-audit":
            result = fetch_prices(config, refresh=False)
            if result["failures"]:
                print(json.dumps(result, indent=2), file=sys.stderr)
                return 1
        bt = run_backtest(config)
        path = write_report(config, bt)
        print(path)
        return 0

    if args.cmd == "diagnostics":
        fetch_prices(config, refresh=False)
        payload = run_diagnostics(config)
        path = write_diagnostics_report(config, payload)
        print(json.dumps({"judgment": payload["judgment"], "report": str(path)}, indent=2))
        return 0

    if args.cmd == "reconcile":
        from .reconciliation import run_reconciliation, write_reconciliation_report

        fetch_prices(config, refresh=False)
        payload = run_reconciliation(config)
        path = write_reconciliation_report(config, payload)
        summary = {
            "judgment": payload["judgment"],
            "agree_rate": payload["signal_agreement"]["agree_qc_bitfinex_vs_ours_weekend"],
            "n_disagree": payload["signal_agreement"]["n_disagree_ours"],
            "sharpe_ours": payload["factorization"]["local_ours_strategy_sharpe"],
            "sharpe_qc_proxy": payload["factorization"]["local_qc_proxy_strategy_sharpe_adj0"],
            "report": str(path),
        }
        print(json.dumps(summary, indent=2))
        return 0

    if args.cmd == "costs":
        from .execution_costs import cost_sweep_qc_proxy, write_costs_report

        fetch_prices(config, refresh=False)
        payload = cost_sweep_qc_proxy(config)
        path = write_costs_report(config, payload)
        print(
            json.dumps(
                {
                    "judgment": payload["judgment"],
                    "timestamp": payload["timestamp_audit"].get("look_ahead_judgment"),
                    "report": str(path),
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "mechanism":
        from .mechanism import run_mechanism, write_mechanism_report

        fetch_prices(config, refresh=False)
        payload = run_mechanism(config)
        path = write_mechanism_report(config, payload)
        print(
            json.dumps(
                {
                    "judgment": payload["judgment"],
                    "partial_r2_return": payload["partial_r2_return_k20"].get("partial_r2"),
                    "partial_r2_vol": payload["partial_r2_vol_k20"].get("partial_r2"),
                    "incremental_oos_r2_mean": payload.get("incremental_oos_r2_mean"),
                    "report": str(path),
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "oos-status":
        from .oos_ledger import ledger_status

        print(json.dumps(ledger_status(config), indent=2))
        return 0

    if args.cmd == "oos-append":
        from .oos_ledger import append_oos_ledger

        fetch_prices(config, refresh=False)
        try:
            result = append_oos_ledger(config, dry_run=args.dry_run)
        except RuntimeError as exc:
            print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2))
        return 0

    if args.cmd == "risk-predict":
        from .risk_prediction import run_risk_prediction, write_risk_pred_report

        fetch_prices(config, refresh=False)
        payload = run_risk_prediction(config)
        path = write_risk_pred_report(config, payload)
        print(
            json.dumps(
                {
                    "judgment": payload["judgment"],
                    "delta_auc_vs_vix_rv_trends": payload["incremental_oos_auc_full_minus_baselines"].get(
                        "vs_vix_rv_trends"
                    ),
                    "report": str(path),
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "risk-matched":
        from .risk_matched import run_risk_matched, write_risk_matched_report

        fetch_prices(config, refresh=False)
        payload = run_risk_matched(config)
        path = write_risk_matched_report(config, payload)
        print(
            json.dumps(
                {
                    "judgment": payload["judgment"],
                    "occupancy_qqq": payload["occupancy_qqq"],
                    "edge_vs_vol_matched": payload["edge_vs_vol_matched"],
                    "report": str(path),
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "timing-attribution":
        from .timing_attribution import run_timing_attribution, write_attribution_report

        fetch_prices(config, refresh=False)
        payload = run_timing_attribution(config)
        path = write_attribution_report(config, payload)
        print(
            json.dumps(
                {
                    "narrative": payload["narrative"],
                    "cagr_edge_pp_vs_vol_matched": payload["cagr_edge_pp_vs_vol_matched"],
                    "full_sample": {
                        "pct_active_from_risk_on": payload["full_sample"]["pct_arithmetic_active_from_on"],
                        "pct_active_from_risk_off": payload["full_sample"]["pct_arithmetic_active_from_off"],
                    },
                    "benchmark_judgment": payload["benchmark_judgment"],
                    "btc_vs_qqq200dma": payload["btc_vs_qqq200dma"],
                    "report": str(path),
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "traditional-combo":
        from .frozen_comparators import run_comparator_audit, write_comparator_report

        fetch_prices(config, refresh=False)
        payload = run_comparator_audit(config)
        path = write_comparator_report(config, payload)
        print(
            json.dumps(
                {
                    "judgment": payload["judgment"],
                    "btc_vs_combo": payload["btc_vs_combo"],
                    "signal_agreement": payload["weekly_signal_agreement_btc_vs_combo"],
                    "report": str(path),
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "oos-propositions":
        from .frozen_comparators import run_oos_propositions, write_propositions_report

        fetch_prices(config, refresh=False)
        payload = run_oos_propositions(config)
        path = write_propositions_report(config, payload)
        oos = payload["propositions"]["oos_btc"]
        print(
            json.dumps(
                {
                    "oos_n_weeks": oos.get("n_weeks"),
                    "oos_status": oos.get("status"),
                    "proposition_passes": {
                        "risk_on": oos.get("proposition_1_risk_on", {}).get("passes"),
                        "risk_off": oos.get("proposition_2_risk_off", {}).get("passes"),
                        "active": oos.get("proposition_3_active_vs_static", {}).get("passes"),
                    },
                    "report": str(path),
                },
                indent=2,
            )
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
