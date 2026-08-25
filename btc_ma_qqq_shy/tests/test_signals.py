"""Unit tests for weekly BTC gate logic."""
from __future__ import annotations

import numpy as np
import pandas as pd

from btc_ma_qqq_shy.signals import btc_daily_signal, build_position_series, weekly_decision_dates


def test_weekly_decision_is_last_session_of_week():
    idx = pd.bdate_range("2024-01-02", periods=10)
    dec = weekly_decision_dates(idx)
    assert len(dec) >= 2
    # each decision should be the max date in its ISO week within idx
    for d in dec:
        week = d.isocalendar()[:2]
        same = [t for t in idx if t.isocalendar()[:2] == week]
        assert d == max(same)


def test_signal_requires_both_sma_and_mom():
    idx = pd.bdate_range("2020-01-01", periods=80)
    px = pd.Series(100.0, index=idx)
    px.iloc[-30:] = np.linspace(100, 130, 30)
    feat = btc_daily_signal(px, sma_window=50, momentum_window=20)
    assert feat["risk_on"].isna().iloc[40]
    assert feat["risk_on"].notna().iloc[-1]
    # rising tape near end should be risk-on once windows valid
    assert bool(feat["risk_on"].iloc[-1]) is True


def test_position_applies_next_session():
    idx = pd.bdate_range("2024-01-01", periods=20)
    risk = pd.Series(False, index=idx)
    # Friday-like: force True on first week last day
    decisions = weekly_decision_dates(idx)
    risk.loc[decisions[0]] = True
    pos = build_position_series(risk, idx, risk_on_asset="QQQ", risk_off_asset="SHY")
    # day of decision still SHY (next-session execution)
    assert pos.loc[decisions[0]] == "SHY"
    after = idx[idx > decisions[0]]
    assert len(after) > 0
    assert pos.loc[after[0]] == "QQQ"
