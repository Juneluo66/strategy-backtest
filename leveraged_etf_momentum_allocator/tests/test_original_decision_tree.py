"""Unit tests for exact decision tree — all terminal branches."""
from __future__ import annotations

import pytest

from original_strategy import DecisionResult, StrategyState, get_max_rsi_asset, select_target

THRESHOLDS = {
    "qqq_rsi_overbought": 81,
    "spy_rsi_overbought": 80,
    "tqqq_rsi_oversold": 30,
    "spy_rsi_oversold": 30,
    "uvxy_high": 74,
    "uvxy_extreme": 84,
    "sqqq_rsi_branch_1": 31,
    "sqqq_rsi_branch_2": 34,
}


def _state(**kwargs) -> StrategyState:
    defaults = dict(
        price_spy=500,
        price_qqq=400,
        price_tqqq=50,
        spy_sma_200=400,
        qqq_sma_20=380,
        tqqq_sma_20=45,
        rsi_qqq=50,
        rsi_spy=50,
        rsi_tqqq=50,
        rsi_sqqq=50,
        rsi_uvxy=50,
        rsi_tecs=40,
        rsi_bsv=35,
    )
    defaults.update(kwargs)
    return StrategyState(**defaults)


# --- Bull branches ---
def test_bull_qqq_rsi_over_81():
    r = select_target(_state(price_spy=500, rsi_qqq=82), THRESHOLDS)
    assert r.target == "UVXY"
    assert r.regime == "BULL"


def test_bull_spy_rsi_over_80():
    r = select_target(_state(price_spy=500, rsi_qqq=81, rsi_spy=81), THRESHOLDS)
    assert r.target == "UVXY"


def test_bull_default_tqqq():
    r = select_target(_state(price_spy=500, rsi_qqq=50, rsi_spy=50), THRESHOLDS)
    assert r.target == "TQQQ"


# --- Bear branches ---
def test_bear_tqqq_rsi_under_30():
    r = select_target(_state(price_spy=300, rsi_tqqq=29), THRESHOLDS)
    assert r.target == "TECL"


def test_bear_spy_rsi_under_30():
    r = select_target(_state(price_spy=300, rsi_tqqq=30, rsi_spy=29), THRESHOLDS)
    assert r.target == "SPXL"


def test_bear_uvxy_high_not_extreme():
    r = select_target(_state(price_spy=300, rsi_tqqq=30, rsi_spy=30, rsi_uvxy=80), THRESHOLDS)
    assert r.target == "UVXY"


def test_bear_uvxy_extreme_qqq_above_sma_sqqq_low():
    r = select_target(
        _state(price_spy=300, rsi_tqqq=30, rsi_spy=30, rsi_uvxy=85, price_qqq=400, rsi_sqqq=30),
        THRESHOLDS,
    )
    assert r.target == "TECS"


def test_bear_uvxy_extreme_qqq_above_sma_sqqq_high():
    r = select_target(
        _state(price_spy=300, rsi_tqqq=30, rsi_spy=30, rsi_uvxy=85, price_qqq=400, rsi_sqqq=31),
        THRESHOLDS,
    )
    assert r.target == "TECL"


def test_bear_uvxy_extreme_qqq_below_sma_tecs_wins():
    r = select_target(
        _state(
            price_spy=300, rsi_tqqq=30, rsi_spy=30, rsi_uvxy=85,
            price_qqq=300, rsi_tecs=50, rsi_bsv=40,
        ),
        THRESHOLDS,
    )
    assert r.target == "TECS"


def test_bear_uvxy_extreme_qqq_below_sma_bsv_wins():
    r = select_target(
        _state(
            price_spy=300, rsi_tqqq=30, rsi_spy=30, rsi_uvxy=85,
            price_qqq=300, rsi_tecs=40, rsi_bsv=50,
        ),
        THRESHOLDS,
    )
    assert r.target == "BSV"


def test_bear_tqqq_above_sma_sqqq_low():
    r = select_target(
        _state(price_spy=300, rsi_tqqq=30, rsi_spy=30, rsi_uvxy=70, price_tqqq=50, rsi_sqqq=33),
        THRESHOLDS,
    )
    assert r.target == "TECS"


def test_bear_tqqq_above_sma_sqqq_high():
    r = select_target(
        _state(price_spy=300, rsi_tqqq=30, rsi_spy=30, rsi_uvxy=70, price_tqqq=50, rsi_sqqq=34),
        THRESHOLDS,
    )
    assert r.target == "TECL"


def test_bear_tqqq_below_sma_max_rsi():
    r = select_target(
        _state(
            price_spy=300, rsi_tqqq=30, rsi_spy=30, rsi_uvxy=70,
            price_tqqq=40, rsi_tecs=45, rsi_bsv=55,
        ),
        THRESHOLDS,
    )
    assert r.target == "BSV"


# --- Equality at thresholds (strict > / <) ---
@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (dict(price_spy=500, rsi_qqq=81, rsi_spy=50), "TQQQ"),
        (dict(price_spy=500, rsi_qqq=50, rsi_spy=80), "TQQQ"),
        (
            dict(price_spy=300, rsi_tqqq=30, rsi_spy=30, rsi_uvxy=70, price_tqqq=50, rsi_sqqq=31),
            "TECS",
        ),
        (
            dict(price_spy=300, rsi_tqqq=30, rsi_spy=30, rsi_uvxy=70, price_tqqq=50, rsi_sqqq=34),
            "TECL",
        ),
    ],
)
def test_threshold_equality(kwargs, expected):
    r = select_target(_state(**kwargs), THRESHOLDS)
    assert r.target == expected


def test_uvxy_equality_84():
    r = select_target(
        _state(price_spy=300, rsi_tqqq=30, rsi_spy=30, rsi_uvxy=84, price_qqq=400),
        THRESHOLDS,
    )
    assert r.target == "UVXY"  # 84 is NOT > 84


def test_max_rsi_tie_tecs_wins():
    t, _ = get_max_rsi_asset(50, 50)
    assert t == "TECS"
