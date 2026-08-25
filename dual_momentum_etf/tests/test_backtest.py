"""Backtest timing: signal close → next open; no look-ahead in scores."""
from __future__ import annotations

import numpy as np
import pandas as pd

from dual_momentum_etf.backtest import run_variant
from dual_momentum_etf.config import load_config
from dual_momentum_etf.signals import build_monthly_signal_panel, month_end_index


def _panels(n_days: int = 600):
    dates = pd.bdate_range("2015-01-01", periods=n_days)
    rng = np.random.default_rng(7)
    cols = {}
    for symbol, drift in [
        ("SPY", 0.0003),
        ("QQQ", 0.0005),
        ("IWM", 0.00025),
        ("VEA", 0.0002),
        ("VWO", 0.00022),
        ("GLD", 0.0001),
        ("IEF", 0.00005),
        ("SGOV", 0.00002),
        ("BIL", 0.000015),
    ]:
        rets = drift + rng.normal(0, 0.008, size=n_days)
        close = 100 * np.cumprod(1 + rets)
        # Open ≈ previous close with tiny gap
        open_ = np.r_[close[0], close[:-1] * (1 + rng.normal(0, 0.0005, size=n_days - 1))]
        cols[symbol] = (open_, close)
    opens = pd.DataFrame({s: v[0] for s, v in cols.items()}, index=dates)
    closes = pd.DataFrame({s: v[1] for s, v in cols.items()}, index=dates)
    return opens, closes


def test_execution_after_signal():
    opens, closes = _panels()
    config = load_config()
    result = run_variant(opens, closes, config, "baseline_6", one_way_bps=0.0)
    targets = result["targets"]
    assert not targets.empty
    assert (targets["execution_date"] > targets["signal_date"]).all()


def test_scores_use_only_month_end_history():
    opens, closes = _panels()
    panel = build_monthly_signal_panel(closes, risk_symbols=["SPY", "QQQ"])
    # For a given month-end, r12m must equal close[t]/close[t-12]-1 from month-end series only
    me = closes["SPY"].groupby(closes.index.to_period("M")).last()
    sample_date = month_end_index(closes.index).tolist()[20]
    row = panel[(panel["date"] == sample_date) & (panel["symbol"] == "SPY")].iloc[0]
    # locate position in me
    pos = list(me.index).index(sample_date.to_period("M"))
    expected = float(me.iloc[pos] / me.iloc[pos - 12] - 1)
    assert abs(row["r12m"] - expected) < 1e-10
