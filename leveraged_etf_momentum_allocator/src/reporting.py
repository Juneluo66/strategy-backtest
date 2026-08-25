"""Report generation helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pandas as pd

from config import ProjectConfig


def write_markdown_report(
    path: Path,
    title: str,
    sections: dict[str, str],
    *,
    status_banner: Optional[str] = None,
) -> None:
    lines = [f"# {title}", ""]
    if status_banner:
        lines.extend([f"> **Status:** {status_banner}", ""])
    for heading, body in sections.items():
        lines.extend([f"## {heading}", "", body.strip(), ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def metrics_table(metrics: dict[str, Any]) -> str:
    rows = [
        ("CAGR (net)", f"{metrics.get('cagr_net', float('nan')):.2%}"),
        ("Sharpe (rf=0)", f"{metrics.get('sharpe_rf0', float('nan')):.2f}"),
        ("Sortino (rf=0)", f"{metrics.get('sortino_rf0', float('nan')):.2f}"),
        ("Max Drawdown", f"{metrics.get('max_drawdown', float('nan')):.2%}"),
        ("Calmar", f"{metrics.get('calmar', float('nan')):.2f}"),
        ("Final Wealth", f"{metrics.get('final_wealth_net', float('nan')):.2f}"),
        ("Annual Turnover", f"{metrics.get('annual_turnover', float('nan')):.2f}"),
    ]
    header = "| Metric | Value |\n|--------|-------|\n"
    body = "\n".join(f"| {k} | {v} |" for k, v in rows)
    return header + body


def dataframe_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No data._"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(lines)


def init_placeholder_reports(config: ProjectConfig) -> None:
    """Write stub reports indicating pending source verification."""
    banner = "PENDING — original QuantConnect rules not yet source-verified"
    stubs = {
        "original_replication.md": "Exact replication reconciliation vs QuantConnect index metrics.",
        "benchmark_comparison.md": "SPY / QQQ / TQQQ / UPRO and equal-weight leveraged basket.",
        "deleveraged_test.md": "Leveraged vs 1x proxy decomposition.",
        "robustness.md": "Parameter perturbation grid (post-replication only).",
        "oos_2026.md": "True out-of-sample 2026 YTD performance.",
        "FINAL_AUDIT.md": "Final classification: REJECTED / DISCOVERY_ONLY / etc.",
    }
    for name, desc in stubs.items():
        write_markdown_report(
            config.reports_dir / name,
            name.replace("_", " ").replace(".md", "").title(),
            {"Overview": desc, "Next Step": "Obtain and verify QuantConnect Strategy #60 source rules."},
            status_banner=banner,
        )
