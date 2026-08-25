"""Tests for predictive helpers."""
from __future__ import annotations

import numpy as np
import pandas as pd

from btc_ma_qqq_shy.hac import ols_newey_west
from btc_ma_qqq_shy.predictive import conditional_forward_table, forward_compound_return


def test_forward_compound_matches_manual():
    idx = pd.bdate_range("2020-01-01", periods=10)
    r = pd.Series(0.01, index=idx)
    fwd = forward_compound_return(r, 3)
    # at t0: (1.01^3 - 1)
    assert abs(fwd.iloc[0] - ((1.01**3) - 1)) < 1e-12


def test_conditional_k1_not_all_nan():
    idx = pd.bdate_range("2020-01-01", periods=80)
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0, 0.01, len(idx)), index=idx)
    sig = pd.Series(rng.random(len(idx)) > 0.5, index=idx)
    tab = conditional_forward_table(sig, r, horizons=(1, 5))
    assert tab.loc[tab["k"] == 1, "E_R_on"].notna().all()


def test_nw_recovers_slope():
    rng = np.random.default_rng(1)
    n = 400
    x = rng.normal(size=n)
    y = 1.0 + 2.0 * x + rng.normal(scale=0.5, size=n)
    fit = ols_newey_west(pd.Series(y), pd.DataFrame({"const": 1.0, "x": x}), lags=3)
    assert fit["ok"]
    assert abs(fit["coef"]["x"] - 2.0) < 0.15
