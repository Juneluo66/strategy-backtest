"""ETF share adapters remain blocked until an audited daily source is authorized."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ShareSourceStatus:
    ready: bool
    reason: str


def share_source_status(*, tushare_token: str | None = None) -> ShareSourceStatus:
    """Refuse production share use without validated daily PIT cache."""
    token = (tushare_token if tushare_token is not None else os.environ.get("TUSHARE_TOKEN") or "").strip()
    if not token:
        return ShareSourceStatus(
            ready=False,
            reason=(
                "No TUSHARE_TOKEN / QMT share dump. Quarterly fund-scale pages cannot "
                "support SHARE_CHG_5D/20D. Keep factors partial_unavailable."
            ),
        )
    return ShareSourceStatus(
        ready=False,
        reason=(
            "TUSHARE_TOKEN is set; run `etf-rotation fetch-non-ohlcv --full` and pass "
            "validation (missing_ratio < 0.05, PIT) before production promotion."
        ),
    )
