import numpy as np
import pandas as pd

from max_effect_vix.factors import max_factor, vix_leverage
from max_effect_vix.portfolio import equal_weights, select_low_max


def test_max_factor_uses_top_five_not_the_last_five():
    returns = pd.Series([0.01, -0.05, 0.03, 0.02, 0.08, 0.00, 0.05])
    value = max_factor(returns, lookback=7, top_returns=5).iloc[-1]
    assert np.isclose(value, np.mean([0.08, 0.05, 0.03, 0.02, 0.01]))


def test_vix_leverage_boundaries_and_interpolation():
    assert vix_leverage(15) == 1.5
    assert vix_leverage(30) == 1.0
    assert vix_leverage(22.5) == 1.25
    assert vix_leverage(None) == 1.0
    assert vix_leverage(12, "deleverage_only") == 1.0
    assert vix_leverage(30, "deleverage_only") == 2 / 3


def test_selection_is_lowest_decile_capped_at_25():
    factor = pd.Series(range(300), index=[f"S{i}" for i in range(300)])
    selected = select_low_max(factor)
    assert len(selected) == 25
    assert selected == [f"S{i}" for i in range(25)]
    assert equal_weights(selected, 1.5).sum() == 1.5
