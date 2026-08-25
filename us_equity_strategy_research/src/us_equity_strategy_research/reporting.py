"""Report writers for strategy audits."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def _md_table(rows: list[dict], columns: list[str]) -> list[str]:
    if not rows:
        return ["_(no rows)_", ""]
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(["---"] * len(columns)) + " |"
    lines = [header, sep]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(c, "")) for c in columns) + " |")
    lines.append("")
    return lines


def write_strategy_report(
    path: Path,
    *,
    title: str,
    rules: list[str],
    data_limits: list[str],
    metrics: dict,
    windows: dict,
    grade: str,
    extras: Optional[list[str]] = None,
) -> Path:
    lines = [
        f"# {title}",
        "",
        f"## Audit grade: `{grade}`",
        "",
        "## Strategy rules",
        "",
        *[f"- {r}" for r in rules],
        "",
        "## Data limits",
        "",
        *[f"- {d}" for d in data_limits],
        "",
        "## Full-sample metrics (net unless noted)",
        "",
        "```json",
        json.dumps(metrics, indent=2, default=str),
        "```",
        "",
        "## Windowed results",
        "",
        "```json",
        json.dumps(windows, indent=2, default=str),
        "```",
        "",
    ]
    if extras:
        lines.extend(extras)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_final_audit(
    path: Path,
    *,
    grades: dict[str, str],
    answers: dict[str, str],
    primary: str,
    shadow: list[str],
    limitations: list[str],
    commands: list[str],
) -> Path:
    lines = [
        "# US Equity Final Audit",
        "",
        "## Per-strategy grades",
        "",
        *[f"- **{k}**: `{v}`" for k, v in grades.items()],
        "",
        "## Research questions",
        "",
        *[f"### {k}\n\n{v}\n" for k, v in answers.items()],
        "",
        f"## Primary paper candidate\n\n`{primary}`\n",
        "## Shadow candidates",
        "",
        *[f"- {s}" for s in shadow],
        "",
        "## Unresolved limitations",
        "",
        *[f"- {x}" for x in limitations],
        "",
        "## Commands",
        "",
        "```bash",
        *commands,
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
