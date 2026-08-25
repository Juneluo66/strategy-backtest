"""Tests for relative-NAV audit definitions and PIT / missing-data guards."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dual_momentum_etf.config import load_config
from dual_momentum_etf.data import load_ohlc
from dual_momentum_etf.relative_spy_audit import (
    metric_a_monthly_return_streak,
    metric_b_rolling_12m_streak,
    metric_c_relative_nav,
    relative_nav_underwater_periods,
)
from dual_momentum_etf.signals import month_end_index, next_trading_day


def test_metric_a_is_monthly_return_streak_not_nav():
    dates = pd.bdate_range("2020-01-01", periods=400)
    # DC flat, SPY up every day -> every month under
    dc = pd.DataFrame(
        {"net_return": 0.0, "equity_net": 1.0},
        index=dates,
    )
    spy_rets = pd.Series(0.001, index=dates)
    spy = pd.DataFrame({"net_return": spy_rets, "equity_net": (1 + spy_rets).cumprod()})
    a = metric_a_monthly_return_streak(dc, spy)
    assert "single-month" in a.definition.lower() or "calendar months" in a.definition.lower()
    assert "NOT relative-NAV" in a.definition
    assert a.longest_months >= 1


def test_relative_nav_includes_ongoing_terminal_period():
    idx = pd.bdate_range("2018-01-01", periods=260)
    # Rise then permanent underperformance vs a rising high
    rel = pd.Series(1.0, index=idx)
    rel.iloc[:50] = np.linspace(1.0, 1.2, 50)
    rel.iloc[50:] = np.linspace(1.19, 0.9, len(idx) - 50)
    periods = relative_nav_underwater_periods(rel)
    assert periods, "expected at least one underwater period"
    assert periods[-1]["ongoing"] is True
    assert periods[-1]["recovery_date"] is None
    assert periods[-1]["duration_months"] >= 1


def test_metric_c_reports_max_and_current_dd():
    dates = pd.bdate_range("2015-01-01", periods=800)
    rng = np.random.default_rng(0)
    dc_r = pd.Series(rng.normal(0.0003, 0.01, len(dates)), index=dates)
    spy_r = pd.Series(rng.normal(0.0004, 0.01, len(dates)), index=dates)
    dc = pd.DataFrame({"net_return": dc_r, "equity_net": (1 + dc_r).cumprod()})
    spy = pd.DataFrame({"net_return": spy_r, "equity_net": (1 + spy_r).cumprod()})
    c = metric_c_relative_nav(dc, spy)
    assert c["max_relative_drawdown"] <= c["current_relative_drawdown"] + 1e-12
    assert c["longest_period"] is not None
    assert "3y" in c["rolling_win_rate_vs_spy"]


def test_month_end_is_last_trading_day_not_calendar_day():
    # Include a month that ends on Sunday
    dates = pd.bdate_range("2021-01-01", "2021-03-31")
    ends = month_end_index(dates)
    for end in ends:
        assert end in dates
        assert end.dayofweek < 5
        # No later trading day in same month
        same = dates[(dates.year == end.year) & (dates.month == end.month)]
        assert end == same.max()


def test_next_open_never_same_day_as_signal():
    dates = pd.DatetimeIndex(pd.bdate_range("2020-01-01", periods=10))
    for i in range(len(dates) - 1):
        nxt = next_trading_day(dates, dates[i])
        assert nxt is not None and nxt > dates[i]


def test_missing_symbol_raises_not_silent_fill():
    config = load_config()
    with pytest.raises(FileNotFoundError):
        load_ohlc(config, symbols=["SPY", "THIS_TICKER_DOES_NOT_EXIST_XYZ"])


def test_metric_b_streak_runs():
    dates = pd.bdate_range("2010-01-01", periods=1500)
    rng = np.random.default_rng(1)
    dc_r = pd.Series(rng.normal(0.0002, 0.01, len(dates)), index=dates)
    spy_r = pd.Series(rng.normal(0.0005, 0.01, len(dates)), index=dates)
    dc = pd.DataFrame({"net_return": dc_r, "equity_net": (1 + dc_r).cumprod()})
    spy = pd.DataFrame({"net_return": spy_r, "equity_net": (1 + spy_r).cumprod()})
    b = metric_b_rolling_12m_streak(dc, spy)
    assert b.longest_months >= 0
    assert "12-month" in b.definition or "12M" in b.definition or "12-month" in b.definition.lower()
