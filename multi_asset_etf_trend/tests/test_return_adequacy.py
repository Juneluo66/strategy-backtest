"""Tests for return-adequacy verdict logic (frozen rules untouched)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from multi_asset_etf_trend.return_adequacy_audit import (
    _sharpe_excess_bil,
    evaluate_adequacy,
    rolling_beat_rate,
)


def test_sharpe_uses_bil_as_rf():
    idx = pd.bdate_range("2020-01-01", periods=252)
    bil = pd.Series(0.00004, index=idx)  # ~1% ann
    strat = bil + 0.0002  # constant excess
    s = _sharpe_excess_bil(strat, bil)
    # zero vol edge case avoided by tiny noise
    strat2 = strat + pd.Series(np.linspace(-1e-6, 1e-6, len(idx)), index=idx)
    s2 = _sharpe_excess_bil(strat2, bil)
    assert np.isfinite(s2) and s2 > 0


def test_rolling_beat_rate_counts():
    idx = pd.bdate_range("2010-01-01", periods=252 * 6)
    s = pd.Series(0.0005, index=idx)
    b = pd.Series(0.0001, index=idx)
    out = rolling_beat_rate(s, b, 3, step=63)
    assert out["n"] > 0
    assert out["beat_rate"] == 1.0


def test_verdict_preservation_path():
    full = pd.DataFrame(
        [
            {
                "strategy": "ensemble_risk_balanced",
                "cagr": 0.045,
                "cagr_minus_bil": 0.032,
                "max_drawdown": -0.08,
                "final_wealth": 2.2,
                "avg_w_bil": 0.38,
            },
            {
                "strategy": "bil_buy_hold",
                "cagr": 0.013,
                "cagr_minus_bil": 0.0,
                "max_drawdown": -0.005,
                "final_wealth": 1.25,
                "avg_w_bil": 1.0,
            },
            {
                "strategy": "sixty_forty_spy_ief_monthly",
                "cagr": 0.085,
                "cagr_minus_bil": 0.072,
                "max_drawdown": -0.31,
                "final_wealth": 4.2,
                "avg_w_bil": 0.0,
            },
        ]
    )
    periods = pd.DataFrame(
        [
            {
                "strategy": "ensemble_risk_balanced",
                "strategy_cagr": 0.04,
                "sixty_forty_cagr": 0.09,
            }
        ]
        * 4
    )
    rolling = {
        "vs_bil_3y": {"beat_rate": 0.85},
        "vs_bil_5y": {"beat_rate": 0.90},
        "vs_60_40_3y": {"beat_rate": 0.15},
        "vs_60_40_5y": {"beat_rate": 0.10},
    }
    decomp = {
        "telescoping_cagr": {
            "timing_vs_passive_equal": -0.02,
            "risk_balance_vs_ensemble_equal": -0.002,
            "passive_risk_premium_vs_bil": 0.045,
        }
    }
    mc = {"final_relative_nav": 1.75}
    v = evaluate_adequacy(full, periods, rolling, decomp, mc)
    assert v["label"] == "CAPITAL_PRESERVATION_CANDIDATE"
