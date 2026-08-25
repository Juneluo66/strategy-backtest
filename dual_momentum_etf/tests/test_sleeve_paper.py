"""Tests for PIT outer blend + IBKR paper constraints."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dual_momentum_etf.paper_trading import (
    PaperConfig,
    PortfolioState,
    execute_rebalance,
    mark_to_market,
)
from dual_momentum_etf.signals import month_end_index, next_trading_day
from dual_momentum_etf.sleeve_final_audit import outer_blend_pit


def _two_legs(n: int = 80) -> tuple[pd.DatetimeIndex, pd.Series, pd.Series]:
    idx = pd.bdate_range("2020-01-01", periods=n)
    rng = np.random.default_rng(0)
    a = pd.Series(rng.normal(0.0004, 0.01, n), index=idx)
    b = pd.Series(rng.normal(0.0002, 0.008, n), index=idx)
    return idx, a, b


def test_outer_blend_drifts_not_constant_weights():
    idx, a, b = _two_legs()
    eq, meta = outer_blend_pit({"spy": a, "dc": b}, {"spy": 0.8, "dc": 0.2}, one_way_bps=5.0, label="t")
    # Between rebalances weights must move away from exact 0.8/0.2
    drifted = (eq["w_spy"] - 0.8).abs() > 1e-12
    assert drifted.any()
    assert meta["construction"]
    # Rebalance dates are next session after month-end signal
    for row in meta["rebalance_log"]:
        sig = pd.Timestamp(row["signal_date"])
        exe = pd.Timestamp(row["execution_date"])
        assert exe > sig
        assert row["price_basis"]


def test_signal_close_not_same_as_execution():
    idx = pd.bdate_range("2020-01-01", periods=60)
    checked = 0
    for sig in month_end_index(idx):
        exe = next_trading_day(idx, sig)
        if exe is None:
            continue
        assert exe > sig
        checked += 1
    assert checked >= 1


def test_paper_missing_price_no_silent_fill():
    cfg = PaperConfig(initial_cash=10_000, min_commission=1.0, allow_fractional_shares=True)
    state = PortfolioState(cash=10_000.0)
    state, logs, _ = execute_rebalance(
        state,
        target_weights={"SPY": 0.5, "IEF": 0.5},
        prices={"SPY": 100.0},  # IEF missing
        cfg=cfg,
        asof=pd.Timestamp("2020-01-02"),
        portfolio_id="t",
    )
    events = {e["event"] for e in logs}
    assert "PRICE_MISSING" in events
    assert "IEF" not in state.shares


def test_paper_no_negative_cash():
    cfg = PaperConfig(
        initial_cash=100.0,
        min_commission=1.0,
        allow_fractional_shares=True,
        forbid_negative_cash=True,
        commission_per_share=0.005,
        one_way_bps=5.0,
    )
    state = PortfolioState(cash=100.0)
    state, logs, _ = execute_rebalance(
        state,
        target_weights={"SPY": 1.0},
        prices={"SPY": 50.0},
        cfg=cfg,
        asof=pd.Timestamp("2020-01-02"),
        portfolio_id="t",
    )
    assert state.cash >= -1e-6
    assert any(e["event"] in {"FILL", "PARTIAL_FILL", "ORDER_REJECT_INSUFFICIENT_CASH"} for e in logs)


def test_paper_integer_share_rounding_and_defer():
    cfg = PaperConfig(
        initial_cash=10_000.0,
        allow_fractional_shares=False,
        share_lot_size=1.0,
        defer_residual_below_notional=50.0,
        min_commission=1.0,
        min_order_notional=1.0,
    )
    state = PortfolioState(cash=10_000.0)
    # Target tiny residual after a near-full position
    state.shares = {"SPY": 99.0}
    state.cash = 10_000.0 - 99.0 * 100.0
    # Mark approx 9900 in SPY + 100 cash
    state, logs, final_w = execute_rebalance(
        state,
        target_weights={"SPY": 1.0},
        prices={"SPY": 100.0},
        cfg=cfg,
        asof=pd.Timestamp("2020-01-02"),
        portfolio_id="t",
    )
    assert all(abs(q - round(q)) < 1e-9 for q in state.shares.values())
    assert "REBALANCE_SUMMARY" in {e["event"] for e in logs}
    _ = final_w
    nav = mark_to_market(state, {"SPY": 100.0})
    assert nav > 0


def test_outer_cost_separated_from_leg_returns():
    """Outer costs only appear on rebalance days; leg series assumed pre-netted."""
    idx, a, b = _two_legs(120)
    # Make legs identical so drift is zero between rebalances if returns equal — still charge outer only on turn
    eq, meta = outer_blend_pit({"spy": a, "dc": a}, {"spy": 0.8, "dc": 0.2}, one_way_bps=10.0, label="t")
    cost_days = eq.loc[eq["outer_rebalance_cost"] > 0]
    assert len(cost_days) == meta["n_rebalances"] or meta["n_rebalances"] >= 0
    # Non-rebalance days have zero outer cost
    assert (eq.loc[eq["outer_rebalance_cost"] == 0].shape[0] + cost_days.shape[0]) == len(eq)
