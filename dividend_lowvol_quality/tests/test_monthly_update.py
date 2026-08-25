import pandas as pd

from strategy_backtest.cli import (
    _append_monthly_universe_audit,
    _monthly_entry_audit,
    _signal_month,
)
from strategy_backtest.config import StrategyConfig


def test_signal_month_normalizes_to_month_start():
    assert _signal_month("2026-07-28") == pd.Timestamp("2026-07-01")


def test_monthly_universe_audit_is_idempotent(tmp_path):
    universe = pd.DataFrame({"code": ["000001", "000002"]})
    _append_monthly_universe_audit(tmp_path, pd.Timestamp("2026-07-01"), universe, tmp_path)
    _append_monthly_universe_audit(tmp_path, pd.Timestamp("2026-07-01"), universe, tmp_path)

    audit = pd.read_csv(tmp_path / "survivorship_audit.csv")
    assert len(audit) == 1
    assert audit.loc[0, "historical_codes"] == 2


def test_monthly_entry_audit_uses_first_session_after_signal(tmp_path):
    cache = tmp_path / "cache"
    (cache / "prices").mkdir(parents=True)
    pd.DataFrame(
        {
            "date": ["2026-07-01", "2026-07-02", "2026-07-03"],
            "open": [10.0, 10.1, 10.2],
            "high": [10.1, 10.2, 10.3],
            "low": [9.9, 10.0, 10.1],
            "close": [10.0, 10.1, 10.2],
            "amount": [100_000_000.0] * 3,
        }
    ).to_parquet(cache / "prices" / "000001_raw.parquet", index=False)
    holdings = pd.DataFrame({"code": ["000001"], "weight": [1.0]})
    config = StrategyConfig(top_n=1, max_industry_weight=1.0, max_stock_weight=1.0)

    audit = _monthly_entry_audit(holdings, pd.Timestamp("2026-07-01"), cache, config)

    assert audit.loc[0, "entry_date"] == pd.Timestamp("2026-07-02")
    assert audit.loc[0, "status"] == "executed"
