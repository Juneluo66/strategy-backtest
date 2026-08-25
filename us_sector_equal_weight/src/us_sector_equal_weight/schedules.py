"""Pre-registered EW9 target schedules (equal weight only; no ranking)."""
from __future__ import annotations

import pandas as pd

from .calendar import month_end_index
from .backtest import run_weight_schedule, buy_and_hold


SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]


def equal_weight_series(symbols: list[str] | None = None) -> pd.Series:
    symbols = list(symbols or SECTORS)
    w = 1.0 / len(symbols)
    return pd.Series({s: w for s in symbols}, dtype=float)


def quarter_end_index(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    ends = month_end_index(dates)
    # Keep month-ends that are calendar quarter ends (Mar/Jun/Sep/Dec)
    return pd.DatetimeIndex([d for d in ends if pd.Timestamp(d).month in (3, 6, 9, 12)])


def year_end_index(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    ends = month_end_index(dates)
    return pd.DatetimeIndex([d for d in ends if pd.Timestamp(d).month == 12])


def build_ew_targets(
    closes: pd.DataFrame,
    *,
    frequency: str,
    symbols: list[str] | None = None,
) -> dict[pd.Timestamp, pd.Series]:
    """
    frequency:
      monthly   — each month-end signal
      quarterly — Mar/Jun/Sep/Dec month-end signal
      annual    — December month-end signal (execute next open ≈ first session of next year)
    """
    symbols = list(symbols or SECTORS)
    series = equal_weight_series(symbols)
    if frequency == "monthly":
        signal_dates = month_end_index(closes.index)
    elif frequency == "quarterly":
        signal_dates = quarter_end_index(closes.index)
    elif frequency == "annual":
        signal_dates = year_end_index(closes.index)
    else:
        raise ValueError(f"unknown frequency {frequency}")
    targets: dict[pd.Timestamp, pd.Series] = {}
    for date in signal_dates:
        if closes.loc[date, symbols].isna().any():
            continue
        targets[pd.Timestamp(date)] = series.copy()
    return targets


VERSION_FREQ = {
    "EW9_monthly": "monthly",
    "EW9_quarterly": "quarterly",
    "EW9_annual": "annual",
}


def run_ew9_version(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    version: str,
    *,
    one_way_bps: float = 5.0,
    execution_delay_sessions: int = 1,
    symbols: list[str] | None = None,
) -> dict:
    if version not in VERSION_FREQ:
        raise ValueError(f"version must be one of {list(VERSION_FREQ)}")
    symbols = list(symbols or SECTORS)
    targets = build_ew_targets(closes, frequency=VERSION_FREQ[version], symbols=symbols)
    out = run_weight_schedule(
        opens,
        closes,
        targets,
        one_way_bps=one_way_bps,
        execution_delay_sessions=execution_delay_sessions,
        symbols=symbols,
    )
    out["version"] = version
    out["frequency"] = VERSION_FREQ[version]
    out["sample_label"] = "DISCOVERY_SAMPLE"
    return out


def run_no_rebalance_basket(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    *,
    symbols: list[str] | None = None,
    one_way_bps: float = 5.0,
    execution_delay_sessions: int = 1,
) -> dict:
    """Buy 1/N once at first eligible signal, then never rebalance (drift only)."""
    symbols = list(symbols or SECTORS)
    ends = month_end_index(closes.index)
    first = None
    for date in ends:
        if not closes.loc[date, symbols].isna().any():
            first = pd.Timestamp(date)
            break
    if first is None:
        raise ValueError("no eligible start for no-rebalance basket")
    targets = {first: equal_weight_series(symbols)}
    out = run_weight_schedule(
        opens,
        closes,
        targets,
        one_way_bps=one_way_bps,
        execution_delay_sessions=execution_delay_sessions,
        symbols=symbols,
    )
    out["version"] = "ew9_no_rebalance_basket"
    return out


def run_spy_monthly_reset(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    *,
    one_way_bps: float = 5.0,
    execution_delay_sessions: int = 1,
) -> dict:
    """Execution-check control: 100% SPY reset each month-end → next open."""
    ends = month_end_index(closes.index)
    targets = {}
    for date in ends:
        if pd.isna(closes.at[date, "SPY"]):
            continue
        targets[pd.Timestamp(date)] = pd.Series({"SPY": 1.0})
    return run_weight_schedule(
        opens,
        closes,
        targets,
        one_way_bps=one_way_bps,
        execution_delay_sessions=execution_delay_sessions,
        symbols=["SPY"],
    )
