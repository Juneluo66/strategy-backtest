"""Unit tests for hard constraints H1–H5 and core strategy gates."""
from __future__ import annotations

import numpy as np
import pandas as pd

from us_equity_strategy_research.backtest.costs import SCENARIOS, trade_cost_fraction
from us_equity_strategy_research.data.membership import force_liquidate_index_exits
from us_equity_strategy_research.data.pead_data import assess_pead_capability
from us_equity_strategy_research.data.prices import cash_symbol_on, common_interval
from us_equity_strategy_research.data.sec_facts import pit_snapshot, validate_facts_frame
from us_equity_strategy_research.data.universe import month_end_index, next_trading_day
from us_equity_strategy_research.factors import momentum_12_1
from us_equity_strategy_research.portfolios import build_portfolios
from us_equity_strategy_research.status import INDEX_EXIT, gate_equity_for_portfolio
from us_equity_strategy_research.strategies import build_momentum_target, build_multifactor_target


def test_index_exit_not_delisting():
    weights = pd.Series({"AAPL": 0.5, "OLD": 0.5})
    members = frozenset({"AAPL"})
    new_w, events = force_liquidate_index_exits(weights, members, pd.Timestamp("2020-01-02"))
    assert "OLD" not in new_w.index
    assert events[0]["event"] == INDEX_EXIT
    assert events[0]["delisting_return_status"] == "UNAVAILABLE"
    assert events[0]["event"] != "DELISTING"


def test_sec_facts_requires_filed_not_period_end():
    facts = pd.DataFrame(
        {
            "cik": [1, 1],
            "concept": ["Assets", "Assets"],
            "end": ["2019-12-31", "2019-12-31"],
            "filed": ["2020-02-15", "2020-03-01"],
            "value": [100.0, 110.0],
        }
    )
    audit = validate_facts_frame(facts)
    assert audit.has_filed
    snap = pit_snapshot(facts, pd.Timestamp("2020-02-20"), concepts=["Assets"])
    assert len(snap) == 1
    assert float(snap.iloc[0]["value"]) == 100.0  # March revision not visible yet
    snap2 = pit_snapshot(facts, pd.Timestamp("2020-03-15"), concepts=["Assets"])
    assert float(snap2.iloc[0]["value"]) == 110.0


def test_sec_facts_blocked_without_filed_column():
    facts = pd.DataFrame({"cik": [1], "concept": ["Assets"], "end": ["2019-12-31"], "value": [1.0]})
    audit = validate_facts_frame(facts)
    assert audit.status == "BLOCKED"


def test_momentum_12_1_skips_recent_month():
    dates = pd.bdate_range("2018-01-01", periods=300)
    closes = pd.DataFrame({"AAA": np.linspace(100, 200, len(dates))}, index=dates)
    # Create a huge last-month jump that 12-1 should skip
    closes.iloc[-5:] = 1000.0
    mom = momentum_12_1(closes, dates[-1], dates)
    # Simple 12m would be huge; 12-1 uses price ~1m ago as end point
    simple_12 = closes.iloc[-1] / closes.iloc[-252] - 1
    assert mom["AAA"] < float(simple_12["AAA"])


def test_signal_next_open_separation():
    dates = pd.bdate_range("2020-01-01", periods=90)
    month_ends = month_end_index(dates)
    # Last month-end may be the calendar's final day — require next open for earlier signals.
    for signal in month_ends[:-1]:
        nxt = next_trading_day(dates, signal)
        assert nxt is not None
        assert nxt > signal


def test_cash_sgov_proxy_and_common_interval():
    dates = pd.bdate_range("2019-01-01", periods=400)
    closes = pd.DataFrame(
        {
            "SGOV": [np.nan] * 300 + list(np.linspace(100, 110, 100)),
            "BIL": np.linspace(100, 105, 400),
            "VTI": np.linspace(100, 200, 400),
        },
        index=dates,
    )
    early = cash_symbol_on(dates[10], closes)
    late = cash_symbol_on(dates[-1], closes)
    assert early == "BIL"
    assert late == "SGOV"
    start, _end = common_interval({"a": closes["VTI"], "b": closes["SGOV"].dropna()})
    assert start >= closes["SGOV"].dropna().index.min()


def test_costs_not_flat_one_bp():
    base = trade_cost_fraction(1.0, scenario=SCENARIOS["baseline"], avg_adv_participation=0.0)
    stress = trade_cost_fraction(1.0, scenario=SCENARIOS["stress"], avg_adv_participation=0.02)
    assert stress > base
    assert base != 0.0001  # not universal 1bp


def test_a_and_b_quality_blocked_without_fundamentals():
    dates = pd.bdate_range("2019-01-01", periods=300)
    closes = pd.DataFrame({"AAA": np.linspace(10, 20, 300), "BBB": np.linspace(10, 15, 300)}, index=dates)
    eligible = pd.Series(True, index=closes.columns)
    a = build_multifactor_target(closes, dates[-1], eligible, set(), fundamentals_ok=False)
    assert a.status == "BLOCKED"
    b1 = build_momentum_target(closes, dates[-1], eligible, set(), variant="B1", quality_ok=False)
    assert b1.status == "BLOCKED"
    b0 = build_momentum_target(closes, dates[-1], eligible, set(), variant="B0", quality_ok=False)
    assert b0.status == "OK"


def test_pead_blocked_without_consensus():
    cap = assess_pead_capability()
    assert cap.formal_status == "BLOCKED"


def test_portfolio_gate_rejects_research_only_and_proxy():
    assert not gate_equity_for_portfolio("RESEARCH ONLY")
    assert not gate_equity_for_portfolio("PASS", is_pead_proxy=True)
    assert gate_equity_for_portfolio("PASS")
    vti = pd.Series(0.01, index=pd.bdate_range("2021-01-01", periods=10))
    ports = build_portfolios(
        vti=vti,
        spy=vti,
        dc=vti,
        equity=vti,
        equity_grade="RESEARCH ONLY",
        equity_is_pead_proxy=False,
    )
    assert ports["P2"].empty or str(ports["P2"].name).startswith("SKIPPED")


def test_weight_sum_equal_weight_caps():
    from us_equity_strategy_research.strategies import equal_weight_caps

    w = equal_weight_caps([f"S{i}" for i in range(40)], max_single=0.04)
    assert abs(w.sum() - 1.0) < 1e-9
    assert (w <= 0.04 + 1e-9).all()
