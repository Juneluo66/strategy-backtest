"""Data completeness checks used to select a defensible backtest window."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def scan_cache_coverage(cache_dir: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    """Report per-source coverage without assuming data is complete."""
    root = Path(cache_dir)
    rows = []
    patterns = {
        "prices_raw": "prices/*_raw.parquet",
        "prices_adjusted": "prices/*_qfq.parquet",
        "dividends": "dividends/*.parquet",
        "cashflow": "financials/*_cashflow.parquet",
        "profit": "financials/*_profit.parquet",
    }
    for source, pattern in patterns.items():
        files = list(root.glob(pattern))
        starts, ends, records = [], [], 0
        for path in files:
            frame = pd.read_parquet(path)
            records += len(frame)
            date_col = next((c for c in ("date", "日期", "公告日期", "实施方案公告日期", "报告日", "报告期") if c in frame.columns), None)
            if date_col:
                dates = pd.to_datetime(frame[date_col], errors="coerce").dropna()
                if not dates.empty:
                    starts.append(dates.min())
                    ends.append(dates.max())
        rows.append(
            {
                "source": source,
                "files": len(files),
                "records": records,
                "start": min(starts) if starts else pd.NaT,
                "end": max(ends) if ends else pd.NaT,
            }
        )
    coverage = pd.DataFrame(rows)
    required = {"prices_raw", "prices_adjusted", "dividends", "cashflow", "profit"}
    complete = coverage.set_index("source")
    # A single-stock smoke cache validates parsing but cannot form the
    # configured 25-name portfolio.
    ready = all(int(complete.loc[name, "files"]) >= 25 for name in required)
    return coverage, {
        "strict_pit_ready": ready,
        "recommended_target_start": "2016-01-01",
        "recommended_target_end": "2025-12-31",
        "selection_rule": "earliest month with 12 consecutive months and >=25 fully PIT-eligible stocks",
    }


def select_window(coverage: pd.DataFrame, monthly_candidates: pd.DataFrame, top_n: int = 25) -> dict[str, object]:
    """Choose the first 12-month eligible run, capped to a 2016–2025 target."""
    if monthly_candidates.empty or "date" not in monthly_candidates:
        return {"status": "insufficient_data", "start": None, "end": None}
    frame = monthly_candidates.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.to_period("M")
    good = frame.set_index("date")["eligible_candidates"].ge(top_n)
    streak = 0
    start = None
    previous = None
    for month, is_good in good.items():
        contiguous = previous is not None and month == previous + 1
        streak = streak + 1 if is_good and contiguous else (1 if is_good else 0)
        if streak >= 12:
            start = month - 11
            break
        previous = month
    if start is None:
        return {"status": "insufficient_data", "start": None, "end": None}
    end = good.index.max()
    return {"status": "ready", "start": str(start), "end": str(end)}
