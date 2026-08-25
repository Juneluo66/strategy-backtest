"""CLI for low_max_defensive research."""
from __future__ import annotations

import argparse
from typing import Optional

from .research import run_research


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Low-MAX defensive equity research (frozen MAX)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    research = sub.add_parser("research", help="Run phases 1–7 purchase-gate style research")
    research.set_defaults(func=lambda _: print(run_research()) or 0)
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
