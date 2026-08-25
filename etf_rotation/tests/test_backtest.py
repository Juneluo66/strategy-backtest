from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from etf_rotation.backtest import event_backtest, vector_backtest
from etf_rotation.config import frozen_config
from etf_rotation.factors import FactorAvailabilityError, cross_sectional_scores, factor_panel


def _prices() -> dict[str, pd.DataFrame]:
    dates = pd.date_range("2020-01-01", periods=80, freq="B")
    result = {}
    for index, code in enumerate(["510300", "159915", "512480", "588000"]):
        close = 100 + index + np.arange(len(dates)) * (0.1 + index * 0.02)
        result[code] = pd.DataFrame({
            "date": dates, "code": code, "open": close * 0.999, "close": close,
            "high": close * 1.01, "low": close * 0.99, "amount": 1e8, "volume": 1e6,
        })
    return result


def test_factor_scores_and_both_engines_run() -> None:
    prices = _prices()
    panel = factor_panel(prices)
    scores, audit = cross_sectional_scores(panel, ["MOM_20D"], [1], [1], run_mode="baseline")
    assert audit.reproduction_status == "BASELINE_OHLCV"
    config = replace(frozen_config(lookback=20), lookback=20, frequency=5)
    vec = vector_backtest(scores, prices, config)
    evt = event_backtest(scores, prices, config)
    assert not vec["equity"].empty
    assert not evt["equity"].empty
    assert {"total_return", "sharpe"}.issubset(vec["metrics"])
    assert (vec["targets"]["execution_date"].notna()).any()


def test_missing_non_ohlcv_factors_are_not_silently_dropped() -> None:
    panel = factor_panel(_prices())
    with pytest.raises(FactorAvailabilityError):
        cross_sectional_scores(
            panel, ["ADX_14D", "MARGIN_BUY_RATIO"], [1, -1], [1, 1], run_mode="research"
        )
    scored, audit = cross_sectional_scores(
        panel, ["ADX_14D"], [1], [1], run_mode="baseline"
    )
    assert audit.actual_factors == ["ADX_14D"]
    assert scored["available_factor_count"].iloc[-1] == 1
