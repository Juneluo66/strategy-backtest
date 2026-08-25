"""CLI for US sector ETF momentum research track."""
from __future__ import annotations

import argparse
import json
import sys

from .audit import run_full_audit
from .config import load_config
from .data import audit_prices, fetch_prices, load_ohlc, reuse_sibling_caches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="us-sector-momentum")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="Download/reuse Yahoo caches (fail-loud)")
    p_fetch.add_argument("--refresh", action="store_true")

    sub.add_parser("audit-data", help="Audit Adj Close / scaled Open / common interval / hashes")

    p_audit = sub.add_parser("full-audit", help="Run three frozen versions + stability + gate")
    p_audit.add_argument("--refresh", action="store_true")

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
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in (
                        "status",
                        "common_start",
                        "common_end",
                        "common_rows",
                        "n_extreme_flags",
                        "n_split_like_flags",
                    )
                },
                indent=2,
            )
        )
        print(f"wrote {out}")
        return 0

    if args.command == "full-audit":
        result = run_full_audit(config, refresh=args.refresh)
        print(
            json.dumps(
                {
                    "gate": result["gate"]["label"],
                    "n_pass": result["gate"]["n_pass"],
                    "n_checks": result["gate"]["n_checks"],
                    "run_dir": result["run_dir"],
                    "common_start": result["common_start"],
                    "ibkr_modified": result["ibkr_modified"],
                },
                indent=2,
            )
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
