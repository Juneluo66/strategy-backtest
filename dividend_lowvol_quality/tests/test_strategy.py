import numpy as np
import pandas as pd

from strategy_backtest.config import StrategyConfig
from strategy_backtest.strategies.dividend_lowvol_quality import select_portfolio


def test_selection_uses_quality_filters_and_respects_weight_caps():
    rows = []
    for index in range(30):
        rows.append(
            {
                "code": f"{index:06d}",
                "industry": f"行业{index % 5}",
                "annual_dividend_yield": 0.08 - index * 0.001,
                "consecutive_years": 3,
                "volatility": 0.1 + index * 0.001,
                "free_cash_flow": 100,
                "earnings_stability": 0.1,
                "listing_days": 1_000,
                "average_turnover": 10_000_000,
                "is_st": False,
            }
        )
    rows[0]["is_st"] = True
    snapshot = pd.DataFrame(rows)
    config = StrategyConfig(top_n=25, max_industry_weight=0.20, max_stock_weight=0.10)

    holdings = select_portfolio(snapshot, config)

    assert len(holdings) == 25
    assert np.isclose(holdings["weight"].sum(), 1.0)
    assert holdings["weight"].max() <= 0.10 + 1e-9
    assert holdings.groupby("industry")["weight"].sum().max() <= 0.20 + 1e-9
    assert "000000" not in set(holdings["code"])


def test_dividend_baseline_uses_equal_weights_without_quality_filter():
    snapshot = pd.DataFrame(
        {
            "code": [f"{index:06d}" for index in range(1, 6)],
            "industry": ["A", "A", "B", "B", "C"],
            "annual_dividend_yield": [0.08, 0.07, 0.06, 0.05, 0.04],
            "consecutive_years": [0] * 5,
            "volatility": [0.2, 0.1, 0.3, 0.25, 0.15],
            "free_cash_flow": [-1.0] * 5,
            "earnings_stability": [np.nan] * 5,
            "listing_days": [500] * 5,
            "average_turnover": [10_000_000] * 5,
            "is_st": [False] * 5,
        }
    )
    holdings = select_portfolio(
        snapshot, StrategyConfig(top_n=3, variant="dividend", weighting="equal")
    )

    assert len(holdings) == 3
    assert np.allclose(holdings["weight"], [1 / 3] * 3)


def test_strict_b_screens_high_dividend_before_low_volatility_selection():
    snapshot = pd.DataFrame(
        {
            "code": [f"{index:06d}" for index in range(1, 11)],
            "industry": [f"I{index}" for index in range(10)],
            "annual_dividend_yield": [0.01] * 10,
            "implemented_ttm_yield": [0.10, 0.09, 0.08, 0.07, 0.06, 0.05, 0.04, 0.03, 0.02, 0.01],
            "consecutive_years": [0] * 10,
            "volatility": [0.5, 0.4, 0.3, 0.2, 0.1, 0.01, 0.02, 0.03, 0.04, 0.05],
            "free_cash_flow": [-1.0] * 10,
            "earnings_stability": [np.nan] * 10,
            "listing_days": [500] * 10,
            "average_turnover": [10_000_000] * 10,
            "is_st": [False] * 10,
            "trade_status": [True] * 10,
        }
    )
    holdings = select_portfolio(
        snapshot,
        StrategyConfig(
            top_n=2,
            variant="strict_b",
            weighting="equal",
            high_dividend_percentile=0.20,
            max_industry_weight=1.0,
            max_stock_weight=1.0,
        ),
    )

    # Codes 1 and 2 are the top dividend quintile even though lower-yield
    # names have lower volatility; the second stage ranks only the quintile.
    assert holdings["code"].tolist() == ["000002", "000001"]
