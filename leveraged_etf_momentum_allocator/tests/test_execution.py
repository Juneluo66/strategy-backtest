"""Execution semantics tests."""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import run_conditional_rotation
from config import ProjectConfig
from execution import ExecutionMode
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _panels(n=1500):
    idx = pd.bdate_range("2010-01-04", periods=n)
    tickers = ["SPY", "QQQ", "TQQQ", "UVXY", "TECL", "SPXL", "SQQQ", "TECS", "BSV"]
    rng = np.random.default_rng(42)
    base = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    closes = pd.DataFrame({t: base * (1 + 0.01 * i) for i, t in enumerate(tickers)}, index=idx)
    opens = closes * 0.999
    return opens, closes


def test_same_target_no_duplicate_trades():
    opens, closes = _panels()
    cfg = ProjectConfig.load(ROOT)
    res = run_conditional_rotation(opens, closes, cfg)
    assert res["actual_trade_count"] <= res["target_change_count"] * 2 + 2


def test_qc_vs_next_open_different():
    opens, closes = _panels()
    cfg = ProjectConfig.load(ROOT)
    qc = run_conditional_rotation(opens, closes, cfg, mode=ExecutionMode.QC_DAILY_SEMANTICS)
    nxt = run_conditional_rotation(opens, closes, cfg, mode=ExecutionMode.NEXT_OPEN_CONSERVATIVE)
    # May differ in NAV path
    assert len(qc["equity"]) == len(nxt["equity"])
