"""Regression tests for Metric C relative NAV (forbid arithmetic-excess wealth path)."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from us_equity_strategy_research.analytics import (
    FORBIDDEN_RELATIVE_WEALTH_FORMULA,
    build_metric_c_relative_frame,
    legacy_arithmetic_excess_relative_path,
    metric_c_relative_stats,
    relative_to_benchmark,
)

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "us_equity_strategy_research"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "half_protect_metric_c_golden.json"


def _series(vals, start="2010-01-04"):
    idx = pd.bdate_range(start, periods=len(vals))
    return pd.Series(vals, index=idx, dtype=float)


def test_legacy_approx_differs_from_metric_c_on_distinct_paths():
    rng = np.random.default_rng(7)
    n = 500
    s = _series(rng.normal(0.0006, 0.012, n))
    b = _series(rng.normal(0.0004, 0.010, n))
    mc = metric_c_relative_stats(s, b)
    legacy = legacy_arithmetic_excess_relative_path(s, b)
    assert abs(mc["final_relative_nav"] - legacy["final_approx_relative"]) > 1e-4


def test_final_relative_nav_equals_end_nav_ratio():
    s = _series([0.01, -0.02, 0.015, 0.0, 0.01] * 20)
    b = _series([0.005, 0.0, 0.01, -0.01, 0.008] * 20)
    frame = build_metric_c_relative_frame(s, b)
    expected = float(frame["strategy_nav"].iloc[-1] / frame["benchmark_nav"].iloc[-1])
    assert frame["relative_nav"].iloc[-1] == pytest.approx(expected)
    assert metric_c_relative_stats(s, b)["final_relative_nav"] == pytest.approx(expected)


def test_identical_returns_relative_nav_is_one():
    r = _series([0.001, -0.002, 0.003, 0.0, 0.001] * 30)
    frame = build_metric_c_relative_frame(r, r.copy())
    assert np.allclose(frame["relative_nav"].to_numpy(), 1.0)
    assert metric_c_relative_stats(r, r.copy())["final_relative_nav"] == pytest.approx(1.0)
    assert metric_c_relative_stats(r, r.copy())["relative_max_dd"] == pytest.approx(0.0)


def test_constant_lead_grows_relative_nav():
    n = 100
    b = _series([0.001] * n)
    s = _series([0.002] * n)  # always +10bp vs bench daily
    frame = build_metric_c_relative_frame(s, b)
    assert frame["relative_nav"].iloc[-1] > frame["relative_nav"].iloc[0]
    # Exact: ((1.002)/(1.001))**(n-0) after rebase both start at 1 after day0
    # After rebase to first day=1, growth from day0 to end:
    ratio = (1.002 / 1.001) ** (n - 1)
    assert frame["relative_nav"].iloc[-1] == pytest.approx(ratio, rel=1e-10)


def test_both_rebased_to_one_at_common_start():
    s = _series([0.01, 0.02, -0.01, 0.0, 0.005] * 10)
    b = _series([0.0, 0.01, 0.01, -0.02, 0.003] * 10)
    frame = build_metric_c_relative_frame(s, b)
    assert frame["strategy_nav"].iloc[0] == pytest.approx(1.0)
    assert frame["benchmark_nav"].iloc[0] == pytest.approx(1.0)
    assert frame["relative_nav"].iloc[0] == pytest.approx(1.0)


def test_strict_intersection_on_misaligned_dates():
    s = _series([0.01] * 10, start="2015-01-05")
    b = _series([0.01] * 10, start="2015-01-08")
    frame = build_metric_c_relative_frame(s, b)
    common = s.index.intersection(b.index)
    assert list(frame.index) == list(common)
    assert len(frame) < len(s)


def test_nan_not_silently_filled_as_zero_return():
    idx = pd.bdate_range("2015-01-05", periods=8)
    s = pd.Series([0.01, np.nan, 0.02, 0.0, -0.01, 0.01, 0.0, 0.01], index=idx)
    b = pd.Series([0.0, 0.0, 0.01, 0.0, 0.0, 0.0, 0.01, 0.0], index=idx)
    frame = build_metric_c_relative_frame(s, b)
    # NaN row dropped — length 7, not 8 with a fabricated 0
    assert len(frame) == 7
    assert not frame["strategy_return"].isna().any()


def test_underwater_units_trading_calendar_months_distinct():
    # Rise then long relative drawdown spanning weekends
    idx = pd.bdate_range("2018-01-02", periods=260)
    rel_drive_s = pd.Series(0.002, index=idx)
    rel_drive_b = pd.Series(0.001, index=idx)
    # After peak, strategy underperforms
    rel_drive_s.iloc[40:] = -0.0005
    rel_drive_b.iloc[40:] = 0.001
    mc = metric_c_relative_stats(rel_drive_s, rel_drive_b)
    assert mc["relative_underwater_trading_sessions"] > 0
    assert mc["relative_underwater_calendar_days"] >= mc["relative_underwater_trading_sessions"] - 1
    assert mc["relative_underwater_months"] >= 1
    # Alias days == trading sessions
    assert mc["relative_underwater_days"] == mc["relative_underwater_trading_sessions"]


def test_rel_nav_above_one_can_still_be_underwater_vs_peak():
    idx = pd.bdate_range("2019-01-02", periods=120)
    # Relative peaks early (>1), then partially gives back but stays >1
    s = pd.Series(0.0, index=idx)
    b = pd.Series(0.0, index=idx)
    s.iloc[:30] = 0.01
    b.iloc[:30] = 0.0
    s.iloc[30:80] = -0.0015
    b.iloc[30:80] = 0.0
    s.iloc[80:] = 0.0
    b.iloc[80:] = 0.0
    frame = build_metric_c_relative_frame(s, b)
    assert frame["relative_nav"].max() > frame["relative_nav"].iloc[-1] > 1.0
    assert frame["relative_drawdown"].iloc[-1] < 0
    mc = metric_c_relative_stats(s, b)
    assert mc["final_relative_nav"] > 1.0
    assert mc["currently_underwater"] is True


def test_relative_to_benchmark_uses_metric_c_not_legacy():
    rng = np.random.default_rng(3)
    s = _series(rng.normal(0.0005, 0.01, 400))
    b = _series(rng.normal(0.0003, 0.01, 400))
    out = relative_to_benchmark(s, b)
    mc = metric_c_relative_stats(s, b)
    legacy = legacy_arithmetic_excess_relative_path(s, b)
    assert out["final_relative_nav"] == pytest.approx(mc["final_relative_nav"])
    assert out["relative_max_dd"] == pytest.approx(mc["relative_max_dd"])
    # Must not equal forbidden path when paths differ
    if abs(mc["final_relative_nav"] - legacy["final_approx_relative"]) > 1e-6:
        assert out["final_relative_nav"] != pytest.approx(legacy["final_approx_relative"])


def test_production_source_forbids_arithmetic_excess_wealth_formula():
    """AST/text guard: formal code paths must not implement forbidden wealth cumprod."""
    offenders = []
    for path in SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        # Allow the dedicated deprecated diagnostic function body only.
        if path.name == "__init__.py" and "analytics" in str(path):
            # Split: ensure relative_to_benchmark / build_metric_c do not contain the pattern
            tree = ast.parse(text)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name in {
                        "legacy_arithmetic_excess_relative_path",
                    }:
                        continue
                    if node.name in {
                        "relative_to_benchmark",
                        "build_metric_c_relative_frame",
                        "metric_c_relative_stats",
                        "performance_report",
                    }:
                        segment = ast.get_source_segment(text, node) or ""
                        if "strategy_return - benchmark_return" in segment.replace(" ", ""):
                            offenders.append(f"{path.name}:{node.name}")
                        # classic pattern variants
                        if "(1+excess).cumprod()" in segment.replace(" ", "") and node.name != "legacy_arithmetic_excess_relative_path":
                            # excess wealth path
                            if "1+excess" in segment.replace(" ", "") and "cumprod" in segment:
                                # Only fail if constructing wealth from excess for relative_nav
                                if "rel_nav" in segment or "relative_nav" in segment:
                                    offenders.append(f"{path.name}:{node.name}:excess_cumprod")
            continue
        if "legacy_arithmetic_excess_relative_path" in text and path.name.endswith("half_protect_relative_audit.py"):
            continue
        # Other modules should not invent the forbidden formula for relative wealth
        compact = text.replace(" ", "").replace("\n", "")
        if "(1+r_s-r_b).cumprod()" in compact or "(1+strategy-benchmark).cumprod()" in compact:
            offenders.append(str(path))
    assert not offenders, f"Forbidden relative-wealth formula in: {offenders}"


def test_half_protect_golden_fixture_metric_c():
    assert FIXTURE.exists(), f"missing golden fixture {FIXTURE}"
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    # Structural invariants frozen from Metric C audit (not strategy retune)
    assert golden["metric_c_vs_80"]["final_relative_wealth"] == pytest.approx(1.048729698321955, rel=0, abs=1e-9)
    assert golden["metric_c_vs_80"]["longest_relative_underwater_months_metric_c"] == 210
    assert golden["legacy_diag_vs_80"]["final_approx_relative"] == pytest.approx(0.98418160895287, rel=0, abs=1e-9)
    assert golden["metric_c_vs_80"]["final_relative_wealth"] > 1.0
    assert golden["legacy_diag_vs_80"]["final_approx_relative"] < 1.0
    assert golden["books"]["half_protect"]["cagr"] == pytest.approx(0.12327114583784216, abs=1e-12)
