"""CLI for statistical signal validation."""
from __future__ import annotations

import argparse


def cmd_run_ew9(_: argparse.Namespace) -> int:
    from .ew9_validation import run_ew9_validation

    path = run_ew9_validation()
    print(path)
    return 0


def cmd_full_report(args: argparse.Namespace) -> int:
    # Currently EW9 focus is the full report deliverable; alias.
    return cmd_run_ew9(args)


def cmd_show_trials(_: argparse.Namespace) -> int:
    from .registry import count_trials, load_registry
    import json

    info = count_trials(load_registry())
    print(json.dumps({k: info[k] for k in ("n_trials_total", "by_project", "by_status", "ew9_classification")}, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="ssv-validate")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run-ew9", help="Run EW9 statistical validation battery").set_defaults(func=cmd_run_ew9)
    sub.add_parser("full-report", help="Generate formal SSV report (EW9 focus)").set_defaults(func=cmd_full_report)
    sub.add_parser("show-trials", help="Show trial registry counts").set_defaults(func=cmd_show_trials)
    args = p.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
