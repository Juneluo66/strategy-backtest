"""Gate hard-fail when CAGR does not beat SPY."""
from __future__ import annotations

from us_sector_momentum.audit import evaluate_gate


def _m(**kwargs):
    base = {
        "cagr": 0.08,
        "final_wealth": 5.0,
        "max_drawdown": -0.40,
        "rel_spy_relative_cagr": 0.0,
        "rel_qqq_final_relative_nav": 0.9,
        "beta_qqq": 1.0,
    }
    base.update(kwargs)
    return base


def test_gate_rejects_when_cagr_below_spy():
    metrics = {
        "composite_6_1_12_1_top3": _m(cagr=0.07, final_wealth=4.0, sharpe=1.5),
        "spy_buy_hold": _m(cagr=0.09, final_wealth=6.0, max_drawdown=-0.35),
    }
    stability = {
        "versions": {
            "composite_6_1_12_1_top3": {
                "exclude_last_1y": {"rel_spy_relative_cagr": -0.01},
                "exclude_last_2y": {"rel_spy_relative_cagr": -0.01},
                "exclude_last_3y": {"rel_spy_relative_cagr": -0.01},
                "cost_10bp": {"rel_spy_relative_cagr": -0.01},
                "cost_20bp": {"rel_spy_relative_cagr": -0.01},
                "extra_delay": {"rel_spy_relative_cagr": -0.01},
            }
        },
        "rolling": [],
        "fixed_endpoints": [],
    }
    xlk = {
        "xlk_share_of_excess_cagr": 0.5,
        "excess_cagr_vs_spy_ex_xlk": -0.01,
    }
    gate = evaluate_gate(metrics, stability, xlk)
    assert gate["label"] == "REJECTED"
    assert gate["checks"]["net_cagr_above_spy"] is False
