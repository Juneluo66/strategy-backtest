from pathlib import Path

import pandas as pd

from strategy_backtest.cli import _complete_cached_codes
from strategy_backtest.data.snapshots import load_cached_histories


def _write(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def test_complete_codes_and_filtered_loading_do_not_scan_unrequested_files(tmp_path):
    base_price = pd.DataFrame({"date": ["2024-01-02"], "open": [1.0], "close": [1.0], "amount": [1.0]})
    dividend = pd.DataFrame(
        {"报告时间": ["2023-12-31"], "实施方案公告日期": ["2024-01-01"], "除权日": ["2024-01-02"], "派息比例": [1.0]}
    )
    cashflow = pd.DataFrame(
        {"报告日": ["2023-12-31"], "公告日期": ["2024-01-01"], "经营活动产生的现金流量净额": [1.0]}
    )
    profit = pd.DataFrame({"报告日": ["2023-12-31"], "公告日期": ["2024-01-01"], "净利润": [1.0]})
    for code in ("000001", "000002"):
        _write(base_price, tmp_path / "prices" / f"{code}_raw.parquet")
        _write(base_price, tmp_path / "prices" / f"{code}_qfq.parquet")
        _write(dividend, tmp_path / "dividends" / f"{code}.parquet")
        _write(cashflow, tmp_path / "financials" / f"{code}_cashflow.parquet")
        _write(profit, tmp_path / "financials" / f"{code}_profit.parquet")

    assert _complete_cached_codes(tmp_path) == {"000001", "000002"}
    prices, _, _ = load_cached_histories(tmp_path, ["000001"])

    assert set(prices) == {"000001"}
