"""Metrics calculation tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from metrics import (
    cagr,
    compute_metrics,
    max_drawdown,
    sharpe,
    sortino,
    turnover_stats,
)


def test_cagr_calculation():
    # 252 days of 0.1% daily -> known CAGR
    r = pd.Series([0.001] * 252)
    result = cagr(r)
    expected = (1.001**252) ** (1 / 1) - 1
    assert result == pytest.approx(expected, rel=1e-6)


def test_drawdown_calculation():
    r = pd.Series([0.1, -0.2, 0.05, -0.1])
    dd = max_drawdown(r)
    equity = (1 + r).cumprod()
    expected = (equity / equity.cummax() - 1).min()
    assert dd == pytest.approx(expected)


def test_sharpe_sortino_finite():
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0.0004, 0.01, 500))
    assert np.isfinite(sharpe(r))
    assert np.isfinite(sortino(r))


def test_turnover():
    trades = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-02", "2020-02-03"]),
            "turnover": [0.5, 1.0],
            "commission": [1.0, 2.0],
            "slippage": [0.5, 1.0],
        }
    )
    stats = turnover_stats(trades)
    assert stats["number_of_trades"] == 2
    assert stats["average_turnover"] == pytest.approx(0.75)


def test_compute_metrics_bundle():
    idx = pd.bdate_range("2020-01-02", periods=252)
    r = pd.Series(0.0005, index=idx)
    equity = pd.DataFrame(
        {
            "gross_return": r,
            "net_return": r,
            "exposure": 1.0,
            "cash_ratio": 0.0,
        }
    )
    equity["equity_gross"] = (1 + r).cumprod()
    equity["equity_net"] = equity["equity_gross"]
    m = compute_metrics(equity, pd.DataFrame(), label="test")
    assert m["cagr_net"] > 0
    assert m["time_in_market"] == 1.0
