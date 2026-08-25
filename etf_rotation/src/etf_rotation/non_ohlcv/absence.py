"""Map non-OHLCV download/absence errors to explicit reason codes."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from etf_rotation.factors import MARGIN_ABSENCE_KINDS

# Codes known to be outside the equity margin-target universe for the free Eastmoney
# history used here. Retrying the same endpoint will not create records.
KNOWN_NOT_MARGIN_ELIGIBLE = {
    "159985": "commodity futures ETF (豆粕); Eastmoney margin endpoint returned empty history",
}

# Network / truncated HTTP responses — may be worth a retry, but not proven recoverable.
KNOWN_REQUEST_FAILED = {
    "518880": "Eastmoney response ended prematurely (see download_errors.csv)",
}


def classify_download_error_message(error: str) -> str:
    text = (error or "").lower()
    if any(token in text for token in ("premature", "timeout", "timed out", "connection", "reset", "ssl")):
        return "request_failed"
    if any(token in text for token in ("空", "empty", "no data", "nodata", "无数据")):
        return "source_no_record"
    if any(token in text for token in ("mapping", "not found", "无效代码", "invalid code")):
        return "symbol_mapping_failure"
    return "unknown"


def load_margin_absence_kinds(raw_dir: Path | None = None) -> dict[str, str]:
    """Build code → absence kind from download_errors plus domain overrides."""
    kinds: dict[str, str] = {}
    if raw_dir is not None:
        path = Path(raw_dir) / "download_errors.csv"
        if path.exists():
            frame = pd.read_csv(path)
            for _, row in frame.iterrows():
                code = str(row.get("code", "")).zfill(6)
                field = str(row.get("field", ""))
                if "margin" not in field.lower() and field not in {"rzye", "rzmre", "eastmoney_margin"}:
                    continue
                kinds[code] = classify_download_error_message(str(row.get("error", "")))
    for code, _note in KNOWN_NOT_MARGIN_ELIGIBLE.items():
        kinds[code] = "not_margin_eligible"
    for code, _note in KNOWN_REQUEST_FAILED.items():
        # Preserve request_failed unless a stronger eligibility ruling exists.
        kinds.setdefault(code, "request_failed")
        if code not in KNOWN_NOT_MARGIN_ELIGIBLE:
            kinds[code] = "request_failed"
    for code, kind in kinds.items():
        if kind not in MARGIN_ABSENCE_KINDS:
            kinds[code] = "unknown"
    return kinds


def absence_kind_notes() -> dict[str, str]:
    notes = dict(KNOWN_NOT_MARGIN_ELIGIBLE)
    notes.update(KNOWN_REQUEST_FAILED)
    return notes
