"""Robust core selectors must preserve ORIGINAL when no ablation flags."""
from __future__ import annotations

from original_strategy import StrategyState, select_target
from robust_core import select_target_options


def _state(**kwargs) -> StrategyState:
    base = dict(
        price_spy=100,
        price_qqq=100,
        price_tqqq=100,
        spy_sma_200=90,
        qqq_sma_20=95,
        tqqq_sma_20=95,
        rsi_qqq=50,
        rsi_spy=50,
        rsi_tqqq=50,
        rsi_sqqq=50,
        rsi_uvxy=50,
        rsi_tecs=40,
        rsi_bsv=30,
    )
    base.update(kwargs)
    return StrategyState(**base)


def test_options_match_original_bull_default():
    st = _state(price_spy=110, spy_sma_200=100, rsi_qqq=50, rsi_spy=50)
    thresh = {
        "qqq_rsi_overbought": 81,
        "spy_rsi_overbought": 80,
        "tqqq_rsi_oversold": 30,
        "spy_rsi_oversold": 30,
        "uvxy_high": 74,
        "uvxy_extreme": 84,
        "sqqq_rsi_branch_1": 31,
        "sqqq_rsi_branch_2": 34,
    }
    a = select_target(st, thresh)
    b = select_target_options(st, thresh)
    assert a.target == b.target == "TQQQ"


def test_prune_to_bsv():
    st = _state(price_spy=80, spy_sma_200=100, rsi_tqqq=20)
    thresh = {"tqqq_rsi_oversold": 30}
    d = select_target_options(st, thresh, prune_branches=["B4"])
    assert d.target == "BSV"
    assert "PRUNE_B4" in d.branch_path[-1]
