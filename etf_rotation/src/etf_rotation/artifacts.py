"""Immutable run directories, config snapshots, and execution metadata."""
from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from etf_rotation.config import RotationConfig, load_yaml


def config_hash(config: RotationConfig) -> str:
    """Hash the canonical config plus the immutable universe declaration."""
    frozen = load_yaml(config.project_root / "configs" / "frozen_v8.yaml")
    universe = load_yaml(config.project_root / "configs" / "etf_universe.yaml")
    runtime = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in asdict(config).items()
    }
    payload = yaml.safe_dump(
        {"frozen": frozen, "universe": universe, "runtime": runtime},
        allow_unicode=True,
        sort_keys=True,
        default_flow_style=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def git_commit(project_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def new_run_directory(config: RotationConfig, command: str) -> tuple[str, Path, str]:
    digest = config_hash(config)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}_{command}_{digest[:12]}"
    directory = config.reports_dir / "runs" / run_id
    if directory.exists():
        raise FileExistsError(f"immutable run directory already exists: {directory}")
    directory.mkdir(parents=True)
    snapshot = load_yaml(config.project_root / "configs" / "frozen_v8.yaml")
    with (directory / "config_snapshot.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(snapshot, handle, allow_unicode=True, sort_keys=False)
    (directory / "config_hash.txt").write_text(digest + "\n", encoding="utf-8")
    metadata = {
        "run_id": run_id,
        "command": command,
        "config_hash": digest,
        "git_commit": git_commit(config.project_root),
        "executed_at_utc": stamp,
        "python": sys.version,
        "platform": platform.platform(),
        "data_source": "AkShare/Eastmoney daily ETF qfq OHLCV",
        "seed": 0,
    }
    pd.Series(metadata).to_json(directory / "run_metadata.json", indent=2, force_ascii=False)
    return run_id, directory, digest
