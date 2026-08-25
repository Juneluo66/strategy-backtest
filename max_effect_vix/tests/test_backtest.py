import numpy as np
import pandas as pd

from max_effect_vix.backtest import run_backtest
from max_effect_vix.factors import monthly_signal_dates
from max_effect_vix.status import INDEX_EXIT


def test_signal_dates_are_previous_completed_sessions():
    dates = pd.bdate_range("2024-01-29", periods=7)
    signals = monthly_signal_dates(dates)
    assert list(signals) == [pd.Timestamp("2024-01-31")]


def test_backtest_emits_no_holdings_without_full_21_day_history():
    dates = pd.bdate_range("2024-01-01", periods=20)
    prices = pd.DataFrame({"A": range(100, 120), "B": range(110, 130)}, index=dates, dtype=float)
    results, holdings, trades, exits = run_backtest(
        prices, prices, prices * 100_000, pd.Series(20.0, index=dates)
    )
    assert len(results) == len(dates)
    assert holdings.empty
    assert trades.empty
    assert exits.empty


def test_index_exit_is_audited_not_silently_dropped():
    dates = pd.bdate_range("2023-12-01", periods=90)
    # Low-MAX names A-E: smooth path. High-MAX names F-J: occasional spikes.
    data = {}
    for idx, symbol in enumerate(list("ABCDEFGHIJ")):
        series = np.linspace(100 + idx, 160 + idx, len(dates))
        if symbol >= "F":
            series[30] *= 1.25
            series[60] *= 1.25
        data[symbol] = series
    prices = pd.DataFrame(data, index=dates, dtype=float)
    volumes = prices * 1_000_000
    exit_cut = dates[55]

    def membership(date):
        if date >= exit_cut:
            return frozenset(list("FGHIJ"))
        return frozenset(list("ABCDEFGHIJ"))

    _, holdings, trades, exits = run_backtest(
        prices,
        prices,
        volumes,
        pd.Series(15.0, index=dates),
        lookback=21,
        top_returns=1,
        min_dollar_volume=1.0,
        portfolio_decile=0.5,
        max_portfolio_size=5,
        vix_mode="none",
        membership_on=membership,
    )
    assert not holdings.empty
    assert not exits.empty
    assert set(exits["event"]) == {INDEX_EXIT}
    assert exits["delisting_return_status"].eq("UNAVAILABLE").all()
    assert set(exits["symbol"]).issubset(set("ABCDE"))
    assert not trades.loc[trades["reason"] == INDEX_EXIT].empty
