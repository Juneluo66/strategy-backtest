"""Immutable run artifacts for reproducible research."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .config import DualMomentumConfig, load_yaml


def config_hash(config: DualMomentumConfig) -> str:
    payload = yaml.safe_dump(
        {"frozen": config.raw, "universe": config.universe},
        allow_unicode=True,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def new_run_directory(config: DualMomentumConfig, command: str) -> Path:
    digest = config_hash(config)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = config.reports_dir / "runs" / f"{stamp}_{command}_{digest[:12]}"
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "config_snapshot.yaml").write_text(
        yaml.safe_dump(config.raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (directory / "universe_snapshot.yaml").write_text(
        yaml.safe_dump(config.universe, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (directory / "config_hash.txt").write_text(f"{digest}\n", encoding="utf-8")
    metadata = {
        "command": command,
        "config_hash": digest,
        "git_commit": _git_commit(config.project_root),
        "executed_at_utc": stamp,
        "python": sys.version,
        "platform": platform.platform(),
        "data_source": config.raw["data"]["source"],
    }
    (directory / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return directory


def frozen_snapshot(config: DualMomentumConfig) -> dict:
    return {"frozen": load_yaml(config.project_root / "configs" / "frozen.yaml"), "universe": config.universe}
