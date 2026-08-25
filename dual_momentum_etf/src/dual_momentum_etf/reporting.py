"""Write run CSVs and summary markdown reports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .metrics import performance_report, window_reports


def save_variant_artifacts(directory: Path, result: dict[str, Any], metrics: dict, windows: dict) -> None:
    name = result["variant"]
    result["equity"].to_csv(directory / f"{name}_equity.csv")
    result["targets"].to_csv(directory / f"{name}_targets.csv", index=False)
    result["trades"].to_csv(directory / f"{name}_trades.csv", index=False)
    result["monthly_scores"].to_csv(directory / f"{name}_monthly_scores.csv", index=False)
    if result["audit"] is not None and not result["audit"].empty:
        result["audit"].to_csv(directory / f"{name}_audit.csv", index=False)
    if result["cash_switches"] is not None and not result["cash_switches"].empty:
        result["cash_switches"].to_csv(directory / f"{name}_cash_switches.csv", index=False)
    payload = {"variant": name, "one_way_bps": result["one_way_bps"], "metrics": metrics, "windows": windows}
    (directory / f"{name}_metrics.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def write_summary_md(
    path: Path,
    *,
    variant_metrics: dict[str, dict],
    notes: list[str] | None = None,
) -> None:
    def _fmt(metrics: dict, key: str, kind: str) -> str:
        value = metrics.get(key)
        if value is None or (isinstance(value, float) and value != value):
            return "n/a"
        if kind == "pct":
            return f"{value:.2%}"
        if kind == "pct1":
            return f"{value:.1%}"
        if kind == "num2":
            return f"{value:.2f}"
        return str(value)

    lines = [
        "# Dual Momentum ETF Summary",
        "",
        "Pre-declared variants. Metrics are net of stated one-way costs unless labeled gross.",
        "",
        "| Variant | Net CAGR | Net Vol | Net Sharpe | MaxDD | Ann. Turnover | QQQ held% | SPY+QQQ cohold% | vs SPY Sharpe |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in variant_metrics.items():
        lines.append(
            "| {name} | {cagr} | {vol} | {sharpe} | {dd} | {to} | {qqq} | {co} | {bsharpe} |".format(
                name=name,
                cagr=_fmt(metrics, "net_cagr", "pct"),
                vol=_fmt(metrics, "net_volatility", "pct"),
                sharpe=_fmt(metrics, "net_sharpe", "num2"),
                dd=_fmt(metrics, "net_max_drawdown", "pct"),
                to=_fmt(metrics, "annualized_turnover", "num2"),
                qqq=_fmt(metrics, "qqq_held_pct", "pct1"),
                co=_fmt(metrics, "spy_qqq_cohold_pct", "pct1"),
                bsharpe=_fmt(metrics, "benchmark_sharpe", "num2"),
            )
        )
    lines.extend(["", "## Notes", ""])
    for note in notes or []:
        lines.append(f"- {note}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compute_and_save(
    directory: Path,
    result: dict[str, Any],
    benchmark_close: pd.Series,
    research_windows: dict,
) -> dict:
    equity = result["equity"]
    trades = result["trades"]
    targets = result["targets"]
    metrics = performance_report(equity, trades, targets, benchmark_close)
    windows = {
        name: (bounds[0], bounds[1]) for name, bounds in research_windows.items()
    }
    window_metrics = window_reports(equity, trades, targets, benchmark_close, windows)
    save_variant_artifacts(directory, result, metrics, window_metrics)
    return metrics
