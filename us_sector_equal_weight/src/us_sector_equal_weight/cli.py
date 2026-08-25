"""CLI for us_sector_equal_weight."""
from __future__ import annotations

import argparse
import json

from .config import load_config
from .data import audit_prices, fetch_prices, load_ohlc


def cmd_fetch(args: argparse.Namespace) -> int:
    config = load_config()
    manifest = fetch_prices(config, refresh=bool(args.refresh))
    print(json.dumps({k: manifest.get(k) for k in ("completed_symbols", "failures", "actions")}, indent=2, default=str))
    return 0


def cmd_audit_data(_: argparse.Namespace) -> int:
    config = load_config()
    opens, closes, raw = load_ohlc(config)
    report = audit_prices(config, opens, closes, raw)
    path = config.reports_dir / "data_audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(path)
    return 0


def cmd_full_audit(args: argparse.Namespace) -> int:
    from .audit import run_full_audit

    path = run_full_audit(refresh=bool(args.refresh))
    print(path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="us-sector-ew")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch", help="Fetch/reuse Yahoo ETF prices")
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("audit-data", help="Price panel integrity audit")
    p.set_defaults(func=cmd_audit_data)

    p = sub.add_parser("full-audit", help="Run pre-registered EW9 equal-weight audit")
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_full_audit)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
