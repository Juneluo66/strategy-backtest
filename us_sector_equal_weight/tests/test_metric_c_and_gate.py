"""Metric C and gate smoke tests."""
from __future__ import annotations

import numpy as np
import pandas as pd

from us_sector_equal_weight.gate import evaluate_gate
from us_sector_equal_weight.metrics import metric_c_relative_stats


def test_metric_c_identical_is_one():
    r = pd.Series(np.linspace(0.001, 0.002, 100), index=pd.bdate_range("2015-01-01", periods=100))
    m = metric_c_relative_stats(r, r.copy())
    assert abs(m["final_relative_nav"] - 1.0) < 1e-12


def test_gate_discovery_only_path():
    # Minimal synthetic payload: discovery beats SPY but OOS/rolling fail
    payload = {
        "discovery": {
            "EW9_monthly": {"metrics": {"cagr": 0.12, "sharpe": 0.7, "max_drawdown": -0.4}},
            "EW9_quarterly": {"metrics": {"cagr": 0.119, "sharpe": 0.7, "max_drawdown": -0.4}},
            "EW9_annual": {"metrics": {"cagr": 0.118, "sharpe": 0.7, "max_drawdown": -0.4}},
            "spy_bh": {"metrics": {"cagr": 0.10, "sharpe": 0.6, "max_drawdown": -0.45}},
            "rsp_bh": {"metrics": {"status": "EMPTY"}},
        },
        "pseudo_oos": {
            "2003-01-02": {
                "EW9_monthly": {"cagr": 0.09},
                "spy_bh": {"cagr": 0.10},
            }
        },
        "fixed_endpoints": {},
        "rolling": {"5y": {"win_rate": 0.4}, "10y": {"win_rate": 0.4}},
        "cost_stress": {"10.0": {"EW9_monthly": {"cagr": 0.11}}, "20.0": {"EW9_monthly": {"cagr": 0.105}}},
        "delay_stress": {"EW9_monthly": {"cagr": 0.11}},
        "french": {
            "pre_etf": {"EW9_monthly": {"status": "OK", "cagr": 0.08}},
            "post_etf": {"EW9_monthly": {"status": "OK", "cagr": 0.09}},
        },
        "attribution": {"dominance": {"dominated": False}},
    }
    raw = {
        "gate": {
            "label_pass": "SECTOR_EQUAL_WEIGHT_RETURN_CANDIDATE",
            "label_discovery_only": "DISCOVERY_ONLY",
            "rolling_5y_win_min": 0.55,
            "rolling_10y_win_min": 0.60,
            "maxdd_vs_spy_extra_pp": 0.05,
        }
    }
    g = evaluate_gate(payload, raw)
    assert g["label"] in {"DISCOVERY_ONLY", "REJECT_OR_RESEARCH_ONLY", "SECTOR_EQUAL_WEIGHT_RETURN_CANDIDATE"}
    assert g["checks"]["discovery_cagr_gt_spy"] is True
