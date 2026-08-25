#!/usr/bin/env python3
"""Parameter robustness — only after exact replication."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config import ORIGINAL_ABORT_MESSAGE, ProjectConfig, SourceVerificationError


def main() -> int:
    cfg = ProjectConfig.load(ROOT)
    try:
        cfg.require_original_verification()
    except SourceVerificationError:
        print(ORIGINAL_ABORT_MESSAGE)
        print("Robustness analysis is forbidden before exact replication.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
