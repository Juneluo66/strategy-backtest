#!/usr/bin/env python3
"""Run benchmark grid — available for data that exists in window."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from benchmarks import benchmark_grid
from config import ProjectConfig
from data_loader import fetch_prices, load_panels
from reporting import metrics_table, write_markdown_report


def main() -> int:
    cfg = ProjectConfig.load(ROOT)
    start, end = cfg.backtest_window()
    symbols = ["SPY", "QQQ", "TQQQ", "UPRO"]
    fetch_prices(cfg, symbols=symbols, start="2010-01-01")
    opens, closes, _ = load_panels(cfg, symbols, start=start, end=end)
    grid = benchmark_grid(opens, closes, start=start, end=end, initial_cash=cfg.initial_cash())

    sections = {
        "Overview": "Buy-and-hold benchmarks for ETFs present in the comparison window.",
        "Note": "Equal-weight leveraged basket requires verified original universe.",
    }
    for ticker, result in grid.items():
        sections[ticker] = metrics_table(result["metrics"]) + f"\n\nInception: {result.get('inception')}"

    write_markdown_report(
        cfg.reports_dir / "benchmark_comparison.md",
        "Benchmark Comparison",
        sections,
        status_banner="PARTIAL — original universe not verified",
    )
    print(f"Wrote {cfg.reports_dir / 'benchmark_comparison.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
