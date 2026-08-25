import numpy as np
import pandas as pd
import pytest

from max_effect_vix.neutralization import controlled_factor, residualize, rolling_beta


def test_residualize_removes_linear_control_relationship():
    control = pd.Series(np.arange(20, dtype=float), index=[f"S{i}" for i in range(20)])
    factor = 2 * control + pd.Series(np.sin(np.arange(20)), index=control.index)
    residual = residualize(factor, control, (0.025, 0.975))
    assert abs(residual.corr(control)) < 1e-3


def test_beta_uses_only_completed_window():
    index = pd.bdate_range("2024-01-01", periods=130)
    benchmark = pd.Series(np.linspace(-0.01, 0.01, len(index)), index=index)
    returns = pd.DataFrame({"A": benchmark * 2}, index=index)
    beta = rolling_beta(returns, benchmark, lookback=126, min_observations=126)
    assert beta.iloc[-1, 0] == pytest.approx(2.0)


def test_size_neutral_is_explicitly_blocked_without_pit_market_cap():
    with pytest.raises(RuntimeError, match="BLOCKED_BY_PIT_MARKET_CAP"):
        controlled_factor(pd.Series([1.0]), pd.Series([1.0]), pd.Series([1.0]), "size_neutral", (0.025, 0.975))
