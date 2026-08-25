#!/usr/bin/env python3
"""De-leveraged test — requires verified universe and LEVERAGED_TO_1X_MAP."""
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
        print("De-leveraged test also requires verified universe and documented 1x proxy map.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
