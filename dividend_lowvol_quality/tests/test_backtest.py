import pandas as pd
import pytest

from strategy_backtest.backtest.engine import backtest_monthly
from strategy_backtest.config import StrategyConfig


def _snapshot():
    return pd.DataFrame(
        {
            "code": ["000001"],
            "industry": ["银行"],
            "annual_dividend_yield": [0.05],
            "consecutive_years": [3],
            "volatility": [0.20],
            "free_cash_flow": [100],
            "earnings_stability": [0.10],
            "listing_days": [1_000],
            "average_turnover": [10_000_000],
            "is_st": [False],
        }
    )


def test_backtest_executes_next_session_and_applies_costs():
    prices = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03", "2024-02-01", "2024-02-02", "2024-03-01"],
            "code": ["000001"] * 5,
            "open": [10.0, 10.0, 11.0, 11.0, 12.0],
            "close": [10.0, 10.0, 11.0, 11.0, 12.0],
            "adjusted_close": [10.0, 10.0, 11.0, 11.0, 12.0],
        }
    )
    snapshots = {
        pd.Timestamp("2024-01-02"): _snapshot(),
        pd.Timestamp("2024-02-01"): _snapshot(),
        pd.Timestamp("2024-03-01"): _snapshot(),
    }
    config = StrategyConfig(top_n=1, max_industry_weight=1.0, max_stock_weight=1.0)

    result = backtest_monthly(snapshots, prices, config)
    period = result["periods"].iloc[0]

    assert period["entry_date"] == pd.Timestamp("2024-01-03")
    assert period["exit_date"] == pd.Timestamp("2024-02-02")
    assert period["gross_return"] == pytest.approx(0.1)
    assert period["net_return"] < period["gross_return"]
