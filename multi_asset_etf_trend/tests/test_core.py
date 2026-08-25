"""Unit tests for pre-registered signals, Metric C, and gate invariants."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from multi_asset_etf_trend.backtest import run_weight_schedule
from multi_asset_etf_trend.calendar import month_end_index, next_trading_day
from multi_asset_etf_trend.metrics import build_metric_c_relative_frame, metric_c_relative_stats
from multi_asset_etf_trend.signals import (
    target_base_12m_equal,
    target_ensemble_equal,
    target_ensemble_risk_balanced,
)


def test_base_12m_equal_parks_losers_in_bil_without_renorm():
    risk = [f"A{i}" for i in range(8)]
    slot = 1.0 / 8
    r12 = pd.Series({s: 0.10 for s in risk})
    r12["A0"] = -0.05
    r12["A1"] = 0.01  # below BIL
    bil = 0.02
    w = target_base_12m_equal(risk, "BIL", r12, bil)
    assert abs(w.sum() - 1.0) < 1e-12
    assert w["BIL"] == pytest.approx(2 * slot)
    assert "A0" not in w or w.get("A0", 0) == 0
    assert w["A2"] == pytest.approx(slot)


def test_ensemble_equal_scores():
    risk = [f"A{i}" for i in range(8)]
    slot = 1.0 / 8
    flags = {
        "A0": {3: True, 6: True, 12: True},  # score 1
        "A1": {3: True, 6: False, 12: False},  # 1/3
        "A2": {3: False, 6: False, 12: False},  # 0
    }
    for s in risk[3:]:
        flags[s] = {3: False, 6: False, 12: False}
    w = target_ensemble_equal(risk, "BIL", flags)
    assert w["A0"] == pytest.approx(slot * 1.0)
    assert w["A1"] == pytest.approx(slot * (1 / 3))
    assert "A2" not in w or w.get("A2", 0) == 0
    assert w["BIL"] == pytest.approx(1.0 - slot - slot / 3)
    assert abs(w.sum() - 1.0) < 1e-12


def test_risk_balanced_does_not_renormalize_after_score():
    risk = [f"A{i}" for i in range(8)]
    slot = 1.0 / 8
    # Equal vols → equal base 1/8
    vols = pd.Series({s: 0.20 for s in risk})
    flags = {s: {3: False, 6: False, 12: False} for s in risk}
    flags["A0"] = {3: True, 6: True, 12: True}  # only A0 on
    w = target_ensemble_risk_balanced(risk, "BIL", flags, vols)
    # base_A0 = 1/8, score=1 → weight 1/8, NOT renormalized to 100%
    assert w["A0"] == pytest.approx(slot)
    assert w["BIL"] == pytest.approx(1.0 - slot)
    assert abs(w.sum() - 1.0) < 1e-12
    assert sum(w.get(s, 0) for s in risk) <= 1.0 + 1e-12


def test_risk_balanced_inverse_vol_base_then_score():
    risk = [f"A{i}" for i in range(8)]
    vols = pd.Series({s: 0.20 for s in risk})
    vols["A0"] = 0.10  # lower vol → higher base
    flags = {s: {3: True, 6: True, 12: True} for s in risk}  # all score=1
    w = target_ensemble_risk_balanced(risk, "BIL", flags, vols)
    # With all scores=1, weights == inverse-vol bases, sum to 1, BIL≈0
    assert w["A0"] > w["A1"]
    assert abs(w.sum() - 1.0) < 1e-8
    assert w.get("BIL", 0.0) == pytest.approx(0.0, abs=1e-8)


def test_metric_c_is_nav_ratio_not_arithmetic_excess():
    idx = pd.bdate_range("2020-01-01", periods=10)
    s = pd.Series([0.05] * 10, index=idx)
    b = pd.Series([0.01] * 10, index=idx)
    nav_s = (1 + s).cumprod()
    nav_b = (1 + b).cumprod()
    # Same rebase convention as analytics Metric C
    expected = float((nav_s / nav_s.iloc[0]).iloc[-1] / (nav_b / nav_b.iloc[0]).iloc[-1])
    mc = metric_c_relative_stats(s, b)
    assert mc["final_relative_nav"] == pytest.approx(expected)
    frame = build_metric_c_relative_frame(s, b)
    assert frame["relative_nav"].iloc[-1] == pytest.approx(expected)
    approx = float((1 + s - b).cumprod().iloc[-1])
    assert abs(expected - approx) > 1e-6  # geometric NAV ratio ≠ arithmetic excess path


def test_next_open_execution_no_lookahead_on_signal_day():
    idx = pd.bdate_range("2020-01-01", periods=40)
    rng = np.random.default_rng(0)
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, size=len(idx))))
    closes = pd.DataFrame({"SPY": px, "BIL": 100 + np.arange(len(idx)) * 0.001}, index=idx)
    opens = closes.shift(1).bfill() * 0.999
    # Signal on a month-end: target 100% SPY
    ends = month_end_index(idx)
    signal = pd.Timestamp(ends[0])
    exe = next_trading_day(idx, signal)
    targets = {signal: pd.Series({"SPY": 1.0, "BIL": 0.0})}
    run = run_weight_schedule(opens, closes, targets, one_way_bps=5.0, symbols=["SPY", "BIL"])
    assert exe is not None
    # First equity row should be on/after execution date
    assert run["equity"].index.min() >= exe
    assert not run["trades"].empty
    assert pd.Timestamp(run["trades"].iloc[0]["date"]) == exe


def test_weights_drift_between_rebalances():
    idx = pd.bdate_range("2020-01-01", periods=15)
    closes = pd.DataFrame(
        {
            "A": [100, 110, 121, 121, 121, 121, 121, 121, 121, 121, 121, 121, 121, 121, 121],
            "B": [100] * 15,
            "BIL": [100] * 15,
        },
        index=idx,
    )
    opens = closes.copy()
    # Force overnight=0 by open==prev close; intraday carries move
    opens.iloc[0] = closes.iloc[0]
    for i in range(1, len(idx)):
        opens.iloc[i] = closes.iloc[i - 1]
    signal = idx[0]
    # Execute next day
    targets = {pd.Timestamp(signal): pd.Series({"A": 0.5, "B": 0.5, "BIL": 0.0})}
    run = run_weight_schedule(opens, closes, targets, one_way_bps=0.0, symbols=["A", "B", "BIL"])
    w = run["weights"]
    # After A rises and B flat, weight A should drift above 0.5
    assert w.iloc[-1]["A"] > 0.5
    assert abs(w.iloc[-1].sum() - 1.0) < 1e-8
