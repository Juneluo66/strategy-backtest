import numpy as np
import pandas as pd
import pytest

from strategy_backtest.backtest.regime import (
    _transition_cost,
    compute_regime_signals,
    exposure_target,
    overlay_summary,
    run_continuous_exposure,
    run_overlay,
)
from strategy_backtest.config import StrategyConfig


def _prices(start="2020-01-01", periods=900):
    dates = pd.bdate_range(start, periods=periods)
    close = pd.Series(np.linspace(100, 200, periods), index=dates)
    return pd.DataFrame({"date": dates, "open": close.values, "close": close.values})


def test_regime_signal_is_strictly_prior_to_signal_date():
    broad = _prices()
    divlow = _prices()
    signal = pd.Timestamp("2023-06-01")
    breadth = pd.DataFrame({"signal_date": [signal], "breadth_pct": [0.3]})

    result = compute_regime_signals(broad, divlow, pd.Series([signal]), breadth).iloc[0]

    assert result["as_of_date"] < signal
    assert bool(result["F_breadth40"]) is True


def test_future_market_bar_does_not_change_prior_regime_signal():
    broad = _prices()
    divlow = _prices()
    signal = pd.Timestamp("2023-06-01")
    breadth = pd.DataFrame({"signal_date": [signal], "breadth_pct": [0.3]})
    expected = compute_regime_signals(broad, divlow, pd.Series([signal]), breadth).iloc[0]
    broad.loc[broad["date"] >= signal, "close"] = 1.0
    actual = compute_regime_signals(broad, divlow, pd.Series([signal]), breadth).iloc[0]

    assert actual["as_of_date"] == expected["as_of_date"]
    assert actual["ret120"] == pytest.approx(expected["ret120"])


def test_cash_overlay_reports_cash_streak_and_transition_cost():
    dates = pd.to_datetime(["2024-01-02", "2024-02-01", "2024-03-01"])
    periods = pd.DataFrame(
        {
            "signal_date": dates,
            "next_signal_date": dates + pd.offsets.MonthBegin(1),
            "net_return": [0.02, 0.03, -0.01],
            "turnover": [0.2, 0.2, 0.2],
        }
    )
    signals = pd.DataFrame({"signal_date": dates, "A_ma120": [True, False, False]})
    etf = pd.DataFrame({"signal_date": dates, "etf_gross_return": [0.01, 0.01, 0.01]})
    config = StrategyConfig()
    always = run_overlay(periods, signals, "A_ma120", config, etf, "Always")
    cash = run_overlay(periods, signals, "A_ma120", config, etf, "Cash")

    summary = overlay_summary(cash, always, "all_sample", "2024-07-01")

    assert summary["longest_cash_periods"] == 2
    assert summary["condition_switches"] == 1
    assert cash.loc[1, "overlay_transition_cost"] > 0
    assert cash.loc[1, "net_return"] == pytest.approx(-cash.loc[1, "overlay_transition_cost"])


def test_etf_transition_has_no_stamp_duty():
    config = StrategyConfig()
    etf_cost, _ = _transition_cost("cash", "benchmark", 0.0, config, False)
    stock_exit_cost, _ = _transition_cost("strict_b", "cash", 0.0, config, False)

    assert etf_cost == pytest.approx(config.commission_rate + config.slippage_rate)
    assert stock_exit_cost == pytest.approx(
        config.commission_rate + config.slippage_rate + config.sell_stamp_duty_rate
    )


def test_fixed_exposure_presets_do_not_change_state_thresholds():
    assert exposure_target(True, True, "HardCash") == (1.0, "down_and_weak")
    assert exposure_target(False, False, "HardCash") == (0.0, "other")
    assert exposure_target(False, False, "Soft75") == (0.75, "other")
    assert exposure_target(False, False, "Soft50") == (0.50, "other")
    assert exposure_target(True, False, "TrendScaling") == (0.75, "down_only")
    assert exposure_target(False, True, "TrendScaling") == (0.75, "weak_only")
    assert exposure_target(False, False, "TrendScaling") == (0.50, "other")


def test_continuous_exposure_scales_frozen_returns_and_charges_only_delta():
    dates = pd.to_datetime(["2024-01-02", "2024-02-01", "2024-03-01"])
    periods = pd.DataFrame(
        {
            "signal_date": dates,
            "net_return": [0.04, 0.04, 0.04],
            "turnover": [0.2, 0.2, 0.2],
            "transaction_cost": [0.001, 0.001, 0.001],
        }
    )
    signals = pd.DataFrame(
        {
            "signal_date": dates,
            "D_ret120": [True, False, False],
            "F_breadth40": [True, False, False],
        }
    )
    config = StrategyConfig()
    soft = run_continuous_exposure(periods, signals, "Soft50", config)

    assert list(soft["target_exposure"]) == [1.0, 0.5, 0.5]
    assert soft.loc[0, "net_return"] == pytest.approx(0.04)
    expected_exit = 0.5 * (
        config.commission_rate + config.slippage_rate + config.sell_stamp_duty_rate
    )
    assert soft.loc[1, "overlay_transition_cost"] == pytest.approx(expected_exit)
    assert soft.loc[1, "net_return"] == pytest.approx(0.5 * 0.04 - expected_exit)
    assert soft.loc[2, "overlay_transition_cost"] == 0.0
    assert soft.loc[1, "scaled_strict_transaction_cost"] == pytest.approx(0.0005)


def test_continuous_always_exactly_matches_frozen_strict_b():
    dates = pd.to_datetime(["2024-01-02", "2024-02-01"])
    periods = pd.DataFrame(
        {
            "signal_date": dates,
            "net_return": [0.03, -0.01],
            "turnover": [0.2, 0.4],
            "transaction_cost": [0.001, 0.002],
        }
    )
    signals = pd.DataFrame(
        {"signal_date": dates, "D_ret120": [False, True], "F_breadth40": [False, True]}
    )

    always = run_continuous_exposure(periods, signals, "Always", StrategyConfig())

    assert list(always["net_return"]) == list(periods["net_return"])
    assert (always["overlay_transition_cost"] == 0).all()
    assert (always["target_exposure"] == 1).all()
