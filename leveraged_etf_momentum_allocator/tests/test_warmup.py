"""Warm-up and inception tests."""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import effective_common_start, run_conditional_rotation
from config import ProjectConfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _synthetic_panels(n=1500):
    idx = pd.bdate_range("2010-01-04", periods=n)
    tickers = ["SPY", "QQQ", "TQQQ", "UVXY", "TECL", "SPXL", "SQQQ", "TECS", "BSV"]
    closes = pd.DataFrame({t: np.linspace(100, 200, n) + hash(t) % 10 for t in tickers}, index=idx)
    opens = closes * 0.999
    return opens, closes


def test_effective_start_respects_warmup():
    opens, closes = _synthetic_panels()
    cfg = ProjectConfig.load(ROOT)
    eff = effective_common_start(closes, cfg.universe(), warmup=200)
    assert eff >= closes.index[200]


def test_no_trades_during_warmup():
    opens, closes = _synthetic_panels()
    cfg = ProjectConfig.load(ROOT)
    res = run_conditional_rotation(opens, closes, cfg)
    assert res["first_signal_date"] is not None
    assert pd.Timestamp(res["first_signal_date"]) >= pd.Timestamp(res["effective_start"])
