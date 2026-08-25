"""Immutable run artifacts for reproducible research."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from .config import MaxEffectConfig


def config_hash(config: MaxEffectConfig) -> str:
    canonical = yaml.safe_dump(config.raw, allow_unicode=True, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def new_run_directory(
    config: MaxEffectConfig,
    command: str,
    data_status: str,
    status_block: Optional[dict] = None,
) -> Path:
    digest = config_hash(config)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = config.reports_dir / "runs" / f"{stamp}_{command}_{digest[:12]}"
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "config_snapshot.yaml").write_text(
        yaml.safe_dump(config.raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (directory / "config_hash.txt").write_text(f"{digest}\n", encoding="utf-8")
    metadata = {
        "command": command,
        "config_hash": digest,
        "data_status": data_status,
        "git_commit": _git_commit(config.project_root),
        "executed_at_utc": stamp,
        "python": sys.version,
        "platform": platform.platform(),
    }
    if status_block:
        metadata.update(status_block)
        # Hard guard: historical path must never claim PIT validation or eliminated bias.
        if status_block.get("DATA_TIER") == "HISTORICAL_SP500_APPROX":
            metadata["PIT_VALIDATED"] = False
            metadata["SURVIVORSHIP_BIAS"] = "REDUCED_NOT_ELIMINATED"
    (directory / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return directory
