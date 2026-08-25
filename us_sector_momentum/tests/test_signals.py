"""Unit tests for frozen sector-momentum signal rules."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from us_sector_momentum.config import load_config
from us_sector_momentum.signals import (
    apply_top3_buffer,
    equal_top_n_weights,
    rank_percentile_high_best,
    select_top_n,
    skip_month_total_return,
)


SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]


def test_config_frozen_versions():
    cfg = load_config()
    assert cfg.raw["versions"] == [
        "base_12_1_top3",
        "composite_6_1_12_1_top3",
        "composite_top3_buffer",
    ]
    assert cfg.challenger == "composite_6_1_12_1_top3"
    assert cfg.sectors == SECTORS
    assert cfg.raw["ibkr_modified"] is False


def test_skip_month_return_excludes_recent_month():
    idx = pd.date_range("2000-01-31", periods=14, freq="ME")
    prices = pd.DataFrame({s: np.arange(1, 15, dtype=float) for s in SECTORS}, index=idx)
    r = skip_month_total_return(prices, 12, 1)
    # At last date: close[t-1]/close[t-12]-1 = 13/2 - 1 = 5.5
    assert abs(float(r.iloc[-1]["XLK"]) - 5.5) < 1e-9


def test_rank_percentile_and_top3():
    scores = pd.Series(
        {
            "XLB": 0.1,
            "XLE": 0.2,
            "XLF": 0.3,
            "XLI": 0.4,
            "XLK": 0.9,
            "XLP": 0.5,
            "XLU": 0.6,
            "XLV": 0.7,
            "XLY": 0.8,
        }
    )
    pct = rank_percentile_high_best(scores)
    assert pct["XLK"] == pytest.approx(1.0)
    assert pct["XLB"] == pytest.approx(0.0)
    top = select_top_n(scores, 3)
    assert top == ["XLK", "XLY", "XLV"]
    w = equal_top_n_weights(top, SECTORS, 3)
    assert abs(w.sum() - 1.0) < 1e-12
    assert (w > 0).sum() == 3


def test_buffer_keeps_rank4_and_fills():
    scores = pd.Series(
        {
            "XLB": 0.05,
            "XLE": 0.10,
            "XLF": 0.15,
            "XLI": 0.20,
            "XLK": 0.95,
            "XLP": 0.40,
            "XLU": 0.50,
            "XLV": 0.60,
            "XLY": 0.70,
        }
    )
    # Prev: XLK, XLY, XLP — XLP is rank 5? Order: XLK,XLY,XLV,XLU,XLP → XLP is 5th → drop
    # Ranks: XLK1 XLY2 XLV3 XLU4 XLP5 ...
    prev = ["XLK", "XLY", "XLP"]
    held = apply_top3_buffer(prev, scores, top_n=3, buffer_rank=4)
    assert "XLK" in held and "XLY" in held
    assert "XLP" not in held  # rank 5 > 4
    assert len(held) == 3
    # Fill should prefer next best not held → XLV
    assert "XLV" in held


def test_buffer_keeps_rank4():
    scores = pd.Series(
        {
            "XLB": 0.01,
            "XLE": 0.02,
            "XLF": 0.03,
            "XLI": 0.04,
            "XLK": 1.0,
            "XLP": 0.5,
            "XLU": 0.6,
            "XLV": 0.7,
            "XLY": 0.8,
        }
    )
    # ranks: XLK,XLY,XLV,XLU(4),XLP...
    prev = ["XLK", "XLY", "XLU"]
    held = apply_top3_buffer(prev, scores, top_n=3, buffer_rank=4)
    assert held == ["XLK", "XLY", "XLU"]
