"""Wilder RSI — must match QuantConnect MovingAverageType.Wilders."""
from __future__ import annotations

import numpy as np
import numpy as np
import pandas as pd
import pytest

from indicators import simple_sma, wilder_rsi


def test_wilder_rsi_monotonic_uptrend():
    close = pd.Series(np.linspace(100, 150, 60))
    rsi = wilder_rsi(close, period=10)
    valid = rsi.dropna()
    assert len(valid) > 0
    assert valid.iloc[-1] > 70


def test_wilder_not_simple_rolling():
    close = pd.Series(np.linspace(100, 120, 50) + np.random.default_rng(0).normal(0, 0.5, 50))
    wilder = wilder_rsi(close, 10)
    # Simple rolling RSI would differ
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    simple_avg_gain = gain.rolling(10).mean()
    simple_avg_loss = loss.rolling(10).mean()
    simple_rs = simple_avg_gain / simple_avg_loss
    simple_rsi = 100 - 100 / (1 + simple_rs)
    # At least one point should differ meaningfully
    diff = (wilder - simple_rsi).abs()
    assert diff.iloc[-1] > 0.01 or diff.dropna().max() > 0.01


def test_wilder_insufficient_data():
    close = pd.Series([1, 2, 3, 4, 5])
    rsi = wilder_rsi(close, 10)
    assert rsi.isna().all()


def test_sma_simple():
    s = pd.Series([1, 2, 3, 4, 5])
    sma = simple_sma(s, 3)
    assert sma.iloc[2] == pytest.approx(2.0)
    assert sma.iloc[4] == pytest.approx(4.0)
