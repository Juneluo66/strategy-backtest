import pandas as pd

from strategy_backtest.data.akshare_client import _normalize_cninfo_dividends, _normalize_financials
from strategy_backtest.data.pit import normalize_dividend_events


def test_cninfo_current_column_names_produce_eligible_dividend_events():
    raw = pd.DataFrame(
        {
            "报告时间": ["2023-12-31", "2022-12-31"],
            "实施方案公告日期": ["2024-05-01", "2023-05-01"],
            "除权日": ["2024-05-20", "2023-05-20"],
            "派息比例": [7.0, 5.0],
        }
    )
    normalized = _normalize_cninfo_dividends(raw, "600519")
    eligible, audit = normalize_dividend_events(normalized)

    assert len(eligible) == 2
    assert audit.empty
    assert sorted(eligible["cash_per_share"].tolist()) == [0.5, 0.7]


def test_cashflow_and_profit_merge_has_fcf_and_income():
    cashflow = pd.DataFrame(
        {
            "报告日": ["2023-12-31"],
            "公告日期": ["2024-03-30"],
            "经营活动产生的现金流量净额": [100.0],
            "购建固定资产、无形资产和其他长期资产所支付的现金": [30.0],
        }
    )
    profit = pd.DataFrame({"报告日": ["2023-12-31"], "公告日期": ["2024-03-30"], "净利润": [80.0]})

    result = _normalize_financials(cashflow, profit, "000001")

    assert result.loc[0, "capex"] == 30.0
    assert result.loc[0, "net_income"] == 80.0
