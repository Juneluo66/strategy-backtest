"""CLI for research v2 (does not touch v1)."""
from __future__ import annotations

import argparse
import json
import sys

from .config import V2Config
from .data import fetch_prices
from .matrix import run_matrix, write_matrix_report
from .off_rules import run_off_rules, write_off_rules_report
from .walkforward import run_walkforward, write_walkforward_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="btc-regime-v2")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="Download ETF prices (v2 cache; BTC read-only from v1)")
    p_fetch.add_argument("--refresh", action="store_true")

    sub.add_parser("matrix-train", help="30-combo matrix on TRAIN period")
    sub.add_parser("matrix-test", help="30-combo matrix on TEST (vol-match calibrated on train)")
    sub.add_parser("matrix-full", help="30-combo matrix discovery through test end")
    sub.add_parser("walkforward", help="Anchored walk-forward across all 30 combos")
    sub.add_parser("off-rules", help="QQQ + OFF sleeve tiny rule train/test")
    sub.add_parser("full-audit", help="fetch + matrix train/test + walkforward + off-rules")
    sub.add_parser("frozen-final", help="4 frozen candidates: WF blocks, cross-section, costs")

    args = parser.parse_args(argv)
    config = V2Config()

    if args.cmd == "fetch":
        r = fetch_prices(config, refresh=args.refresh)
        print(json.dumps(r, indent=2))
        return 0 if not r["failures"] else 1

    if args.cmd == "matrix-train":
        fetch_prices(config, refresh=False)
        payload = run_matrix(config, period="train")
        write_matrix_report(config, payload)
        print(json.dumps({"period": "train", "top5": payload["top5_sharpe"]}, indent=2))
        return 0

    if args.cmd == "matrix-test":
        fetch_prices(config, refresh=False)
        payload = run_matrix(config, period="test")
        write_matrix_report(config, payload)
        print(json.dumps({"period": "test", "top5": payload["top5_sharpe"]}, indent=2))
        return 0

    if args.cmd == "matrix-full":
        fetch_prices(config, refresh=False)
        payload = run_matrix(config, period="all")
        write_matrix_report(config, payload)
        print(json.dumps({"period": "all", "top5": payload["top5_sharpe"]}, indent=2))
        return 0

    if args.cmd == "walkforward":
        fetch_prices(config, refresh=False)
        payload = run_walkforward(config)
        write_walkforward_report(config, payload)
        print(json.dumps({"judgment": payload["judgment"], "stable": payload["stable_ranking"][:5]}, indent=2))
        return 0

    if args.cmd == "off-rules":
        fetch_prices(config, refresh=False)
        payload = run_off_rules(config)
        write_off_rules_report(config, payload)
        print(json.dumps({"judgment": payload["judgment"], "train": payload["train"]}, indent=2, default=str))
        return 0

    if args.cmd == "full-audit":
        r = fetch_prices(config, refresh=False)
        if r["failures"]:
            print(json.dumps(r, indent=2), file=sys.stderr)
            return 1
        tr = run_matrix(config, period="train")
        write_matrix_report(config, tr)
        te = run_matrix(config, period="test")
        write_matrix_report(config, te)
        wf = run_walkforward(config)
        write_walkforward_report(config, wf)
        off = run_off_rules(config)
        write_off_rules_report(config, off)
        print(
            json.dumps(
                {
                    "train_top5": tr["top5_sharpe"],
                    "test_top5": te["top5_sharpe"],
                    "walkforward": wf["judgment"],
                    "off_rules": off["judgment"],
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "frozen-final":
        from .frozen_final import run_frozen_final, write_frozen_final_report

        fetch_prices(config, refresh=False)
        payload = run_frozen_final(config)
        write_frozen_final_report(config, payload)
        print(
            json.dumps(
                {
                    "candidates": [c["label"] for c in payload["frozen_candidates"]],
                    "verdicts": payload["verdicts"]["assignments"],
                    "cross_section": payload["cross_sectional"]["judgment"],
                    "report": str(config.reports_dir / "frozen_final.md"),
                },
                indent=2,
            )
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
