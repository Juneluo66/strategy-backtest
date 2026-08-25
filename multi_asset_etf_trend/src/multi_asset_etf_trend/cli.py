"""CLI for multi-asset ETF trend research track."""
from __future__ import annotations

import argparse
import json
import sys

from .audit import run_full_audit
from .config import load_config
from .data import audit_prices, fetch_prices, load_ohlc, reuse_sibling_caches
from .return_adequacy_audit import run_return_adequacy_audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="multi-asset-etf-trend")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="Download/reuse Yahoo caches (fail-loud)")
    p_fetch.add_argument("--refresh", action="store_true", help="Force re-download")

    sub.add_parser("audit-data", help="Audit Close/Adj Close/scaled Open and common interval")
    p_audit = sub.add_parser("full-audit", help="Run pre-registered versions + stability + gate")
    p_audit.add_argument("--refresh", action="store_true")
    p_audit.add_argument("--no-appendix", action="store_true")

    sub.add_parser(
        "return-adequacy-audit",
        help="Frozen-rule return adequacy vs BIL / 60-40 (no parameter search)",
    )

    args = parser.parse_args(argv)
    config = load_config()

    if args.command == "fetch":
        reuse_sibling_caches(config)
        try:
            manifest = fetch_prices(config, refresh=args.refresh)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(manifest, indent=2))
        return 0

    if args.command == "audit-data":
        reuse_sibling_caches(config)
        fetch_prices(config, refresh=False)
        opens, closes, raw = load_ohlc(config)
        report = audit_prices(config, opens, closes, raw)
        out = config.reports_dir / "data_audit.json"
        config.reports_dir.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps({k: report[k] for k in ("status", "common_start", "common_end", "common_rows", "n_extreme_flags")}, indent=2))
        print(f"wrote {out}")
        return 0

    if args.command == "full-audit":
        result = run_full_audit(
            config,
            refresh=args.refresh,
            include_appendix=not args.no_appendix,
        )
        print(json.dumps({"gate": result["gate"]["label"], "run_dir": result["run_dir"], "common_start": result["common_start"]}, indent=2))
        return 0 if result["gate"]["passed"] else 0  # research exit 0 either way

    if args.command == "return-adequacy-audit":
        result = run_return_adequacy_audit(config)
        print(
            json.dumps(
                {
                    "verdict": result["verdict"]["label"],
                    "run_dir": result["run_dir"],
                    "common_start": result["common_start"],
                },
                indent=2,
            )
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
