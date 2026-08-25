"""Unit tests for dual-momentum signals, portfolio rules, and look-ahead safety."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dual_momentum_etf.artifacts import config_hash
from dual_momentum_etf.config import load_config
from dual_momentum_etf.data import cash_symbol_on
from dual_momentum_etf.portfolio import (
    PortfolioState,
    apply_category_constraint,
    choose_holdings,
    hysteresis_select,
)
from dual_momentum_etf.signals import (
    build_monthly_signal_panel,
    month_end_closes,
    month_end_index,
    month_sma,
    next_trading_day,
    rolling_month_return,
)


def _synthetic_closes(n_days: int = 400) -> pd.DataFrame:
    dates = pd.bdate_range("2018-01-01", periods=n_days)
    rng = np.random.default_rng(42)
    data = {}
    for symbol, drift in [
        ("SPY", 0.0004),
        ("QQQ", 0.0006),
        ("IWM", 0.0003),
        ("VEA", 0.0002),
        ("GLD", 0.0001),
    ]:
        rets = drift + rng.normal(0, 0.01, size=n_days)
        data[symbol] = 100 * np.cumprod(1 + rets)
    data["SGOV"] = 100 + np.linspace(0, 2, n_days)
    data["BIL"] = 100 + np.linspace(0, 1.5, n_days)
    return pd.DataFrame(data, index=dates)


def test_month_end_and_returns():
    closes = _synthetic_closes()
    me = month_end_closes(closes[["SPY"]])
    assert list(me.index) == list(month_end_index(closes.index))
    r5 = rolling_month_return(me, 5)
    date = me.index[10]
    expected = me.loc[date, "SPY"] / me.iloc[10 - 5]["SPY"] - 1
    assert r5.loc[date, "SPY"] == pytest.approx(expected)


def test_sma10_and_panel_eligibility():
    closes = _synthetic_closes(500)
    panel = build_monthly_signal_panel(
        closes,
        risk_symbols=["SPY", "QQQ", "IWM", "VEA", "GLD"],
        weight_5m=0.6,
        weight_12m=0.4,
        sma_months=10,
        vol_lookback=60,
        vol_min_obs=40,
    )
    assert {"r5m", "r12m", "score", "sigma_60d", "adjusted_score", "above_ma"}.issubset(panel.columns)
    me = month_end_closes(closes[["SPY"]])
    sma = month_sma(me, 10)
    sample = panel[(panel["symbol"] == "SPY") & panel["sma10"].notna()].iloc[-1]
    assert sample["sma10"] == pytest.approx(float(sma.loc[sample["date"], "SPY"]))


def test_next_open_is_strictly_after_signal():
    dates = pd.DatetimeIndex(pd.bdate_range("2020-01-01", periods=10))
    signal = dates[3]
    nxt = next_trading_day(dates, signal)
    assert nxt == dates[4]
    assert nxt > signal


def test_hysteresis_blocks_small_edge_and_allows_large():
    # Challenger is compared to the weakest incumbent.
    ranked = ["A", "B", "C"]
    state = PortfolioState(holdings=["B", "C"], scores={"B": 0.20, "C": 0.19})
    # A / C - 1 = 0.20/0.19 - 1 ≈ 5.26% > 5% → replace weakest C
    selected, audit = hysteresis_select(
        ranked, {"A": 0.20, "B": 0.20, "C": 0.19}, state, top_k=2, relative_threshold=0.05
    )
    assert "A" in selected
    assert any(a.get("reason") == "hysteresis_replace" for a in audit)
    # A / C - 1 = 0.198/0.19 - 1 ≈ 4.2% < 5% → block
    selected2, audit2 = hysteresis_select(
        ranked, {"A": 0.198, "B": 0.20, "C": 0.19}, state, top_k=2, relative_threshold=0.05
    )
    assert "A" not in selected2
    assert set(selected2) == {"B", "C"}
    assert any(a.get("reason") == "hysteresis_block" for a in audit2)


def test_category_constraint_prevents_spy_qqq():
    day = pd.DataFrame(
        [
            {"symbol": "SPY", "score": 0.3},
            {"symbol": "QQQ", "score": 0.4},
            {"symbol": "VEA", "score": 0.2},
            {"symbol": "GLD", "score": 0.1},
        ]
    )
    category_map = {"SPY": "us", "QQQ": "us", "VEA": "intl", "GLD": "defensive"}
    filtered, audit = apply_category_constraint(day, category_map, "score")
    symbols = set(filtered["symbol"])
    assert "QQQ" in symbols
    assert "SPY" not in symbols
    assert any(a["reason"] == "category_capped" for a in audit)


def test_choose_holdings_cash_fill_when_short_topk():
    day = pd.DataFrame(
        [
            {
                "symbol": "SPY",
                "above_ma": True,
                "trend_consistent": True,
                "score": 0.2,
                "adjusted_score": 10.0,
                "sigma_60d": 0.02,
            },
            {
                "symbol": "QQQ",
                "above_ma": True,
                "trend_consistent": True,
                "score": 0.25,
                "adjusted_score": 8.0,
                "sigma_60d": 0.03,
            },
            {
                "symbol": "VEA",
                "above_ma": False,
                "trend_consistent": True,
                "score": 0.1,
                "adjusted_score": 5.0,
                "sigma_60d": 0.02,
            },
        ]
    )
    category_map = {"SPY": "us", "QQQ": "us", "VEA": "intl"}
    weights, state, audit = choose_holdings(
        day,
        PortfolioState(),
        vol_adjust=True,
        category_constraint=True,
        trend_consistency=False,
        regime_sizing=False,
        top_k=2,
        relative_threshold=0.05,
        category_map=category_map,
        cash_symbol="SGOV",
        use_hysteresis=False,
    )
    assert not (("SPY" in weights) and ("QQQ" in weights))
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    # One eligible after category+MA → 50% risk + 50% cash
    risk = [s for s in weights if s != "SGOV"]
    assert len(risk) == 1
    assert weights[risk[0]] == pytest.approx(0.5)
    assert weights["SGOV"] == pytest.approx(0.5)
    assert any(a.get("reason") == "below_ma" for a in audit)


def test_below_ma_and_vol_missing_excluded():
    day = pd.DataFrame(
        [
            {
                "symbol": "SPY",
                "above_ma": False,
                "trend_consistent": True,
                "score": 0.5,
                "adjusted_score": 20.0,
                "sigma_60d": 0.02,
            },
            {
                "symbol": "GLD",
                "above_ma": True,
                "trend_consistent": True,
                "score": 0.1,
                "adjusted_score": np.nan,
                "sigma_60d": np.nan,
            },
        ]
    )
    weights, _, audit = choose_holdings(
        day,
        PortfolioState(),
        vol_adjust=True,
        category_constraint=False,
        trend_consistency=False,
        regime_sizing=False,
        top_k=2,
        relative_threshold=0.05,
        category_map={},
        cash_symbol="SGOV",
    )
    assert weights == {"SGOV": 1.0}
    reasons = {a["reason"] for a in audit if "symbol" in a}
    assert "below_ma" in reasons
    assert "vol_missing" in reasons


def test_cash_proxy_switches_to_sgov():
    dates = pd.bdate_range("2019-01-01", periods=100)
    closes = pd.DataFrame(
        {
            "BIL": np.linspace(100, 101, 100),
            "SGOV": [np.nan] * 50 + list(np.linspace(100, 101, 50)),
        },
        index=dates,
    )
    config = load_config()
    early = cash_symbol_on(dates[10], config, closes)
    late = cash_symbol_on(dates[80], config, closes)
    assert early == "BIL"
    assert late == "SGOV"


def test_config_hash_stable():
    config = load_config()
    assert config_hash(config) == config_hash(config)
    assert len(config_hash(config)) == 64


def test_regime_sizing_goes_cash_when_none_eligible():
    day = pd.DataFrame(
        [
            {
                "symbol": "SPY",
                "above_ma": False,
                "trend_consistent": False,
                "score": 0.1,
                "adjusted_score": 1.0,
                "sigma_60d": 0.02,
            },
            {
                "symbol": "QQQ",
                "above_ma": False,
                "trend_consistent": False,
                "score": 0.2,
                "adjusted_score": 2.0,
                "sigma_60d": 0.02,
            },
        ]
    )
    weights, _, audit = choose_holdings(
        day,
        PortfolioState(),
        vol_adjust=False,
        category_constraint=False,
        trend_consistency=False,
        regime_sizing=True,
        top_k=2,
        relative_threshold=0.05,
        category_map={},
        cash_symbol="SGOV",
    )
    assert weights == {"SGOV": 1.0}
    assert any(a.get("detail") == "all_risk_below_ma" for a in audit)
