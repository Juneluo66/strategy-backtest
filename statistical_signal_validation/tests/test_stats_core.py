from __future__ import annotations

import numpy as np
import pandas as pd

from statistical_signal_validation.stats_core import (
    block_bootstrap_edges,
    deflated_sharpe_ratio,
    information_ratio,
    newey_west_mean_tstat,
    probabilistic_sharpe_ratio,
    relative_nav_stats,
)


def _series(mu, n=800, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-01", periods=n)
    return pd.Series(rng.normal(mu, 0.01, n), index=idx)


def test_relative_nav_identical_is_one():
    r = _series(0.0004)
    m = relative_nav_stats(r, r.copy())
    assert abs(m["final_relative_wealth"] - 1.0) < 1e-12


def test_newey_west_positive_mean():
    r = _series(0.001)
    out = newey_west_mean_tstat(r)
    assert out["t_stat"] > 0
    assert out["p_value"] < 0.05


def test_bootstrap_probabilities_in_unit_interval():
    s = _series(0.0006, seed=1)
    b = _series(0.0004, seed=2)
    out = block_bootstrap_edges(s, b, block=21, n_boot=50, seed=3)
    assert 0 <= out["prob_cagr_edge_gt_0"] <= 1
    assert 0 <= out["prob_final_rel_gt_1"] <= 1


def test_psr_dsr_run():
    r = _series(0.0005)
    psr = probabilistic_sharpe_ratio(r)
    dsr = deflated_sharpe_ratio(r, n_trials=20)
    assert 0 <= psr["psr"] <= 1
    assert 0 <= dsr["dsr"] <= 1
    assert information_ratio(r - 0) != 0
