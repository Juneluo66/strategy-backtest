"""Trial registry loader and n_trials accounting."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml


def registry_path(project_root: Optional[Path] = None) -> Path:
    root = project_root or Path(__file__).resolve().parents[2]
    return root / "configs" / "trial_registry.yaml"


def load_registry(project_root: Optional[Path] = None) -> dict:
    path = registry_path(project_root)
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def count_trials(registry: dict) -> dict:
    total = 0
    by_project: dict[str, int] = {}
    by_status: dict[str, int] = {}
    rows = []
    for trial in registry.get("trials", []):
        n = int(trial.get("n_counted_as", 1))
        total += n
        proj = trial.get("project", "unknown")
        by_project[proj] = by_project.get(proj, 0) + n
        st = trial.get("status", "unknown")
        by_status[st] = by_status.get(st, 0) + n
        rows.append({**trial, "n_counted_as": n})
    return {
        "n_trials_total": total,
        "by_project": by_project,
        "by_status": by_status,
        "rows": rows,
        "ew9_classification": registry.get("ew9_classification", {}),
    }
