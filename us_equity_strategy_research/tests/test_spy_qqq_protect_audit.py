"""Pre-registered protect weight rules."""
from __future__ import annotations

import pandas as pd

from us_equity_strategy_research.spy_qqq_protect_audit import build_protect_targets


def _toy_closes():
    # 12 month-ends with SPY/QQQ above then below SMA
    dates = pd.bdate_range("2015-01-01", periods=280)
    spy = pd.Series(range(len(dates)), index=dates, dtype=float) + 100
    qqq = spy * 1.1
    # Force a drawdown in last 60 days so SMA breaks
    spy.iloc[-60:] = spy.iloc[-60] * 0.7
    qqq.iloc[-60:] = qqq.iloc[-60] * 0.7
    bil = pd.Series(100.0, index=dates)
    return pd.DataFrame({"SPY": spy, "QQQ": qqq, "BIL": bil})


def test_three_modes_weights_pre_registered():
    closes = _toy_closes()
    # Pick last month-end where both likely broken
    full = build_protect_targets(closes, mode="full_protect", sma_months=10)
    half = build_protect_targets(closes, mode="half_protect", sma_months=10)
    joint = build_protect_targets(closes, mode="joint_half_protect", sma_months=10)
    date = max(full)
    f, h, j = full[date], half[date], joint[date]
    # When both broken: full → 100% BIL; half → 35/15/50; joint → 35/15/50
    if "SPY" not in f.index and "QQQ" not in f.index:
        assert abs(f.get("BIL", 0) - 1.0) < 1e-9
        assert abs(h["SPY"] - 0.35) < 1e-9
        assert abs(h["QQQ"] - 0.15) < 1e-9
        assert abs(h["BIL"] - 0.50) < 1e-9
        assert abs(j["SPY"] - 0.35) < 1e-9
        assert abs(j["QQQ"] - 0.15) < 1e-9
    # Weights always sum to 1
    for w in (f, h, j):
        assert abs(w.sum() - 1.0) < 1e-9
