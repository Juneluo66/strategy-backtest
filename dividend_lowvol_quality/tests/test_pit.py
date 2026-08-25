import pandas as pd
import pytest

from strategy_backtest.data.pit import (
    dividend_metrics_as_of,
    financials_as_of,
    normalize_baostock_dividends,
    normalize_dividend_events,
    quality_metrics_as_of,
)
from strategy_backtest.validation.dividend_audit import audit_dividend_stages


def _events():
    return pd.DataFrame(
        [
            ["000001", 2022, "a", "2023-04-01", "2023-05-01", 0.50, "年度", "已实施"],
            ["000001", 2023, "b", "2024-04-01", "2024-05-01", 0.60, "年度", "已实施"],
            ["000001", 2023, "special", "2024-07-01", "2024-07-10", 1.20, "特别分红", "已实施"],
            ["000001", 2024, "future", "2025-04-01", "2025-05-01", 0.70, "年度", "已实施"],
        ],
        columns=[
            "code",
            "report_year",
            "plan_id",
            "public_date",
            "ex_date",
            "cash_per_share",
            "plan_type",
            "status",
        ],
    )


def test_dividend_signal_excludes_future_and_special_events():
    eligible, audit = normalize_dividend_events(_events())
    metrics = dividend_metrics_as_of(eligible, "000001", "2024-12-31", close=10)

    assert len(eligible) == 3
    assert audit["audit_reason"].tolist() == ["special_dividend"]
    assert metrics["annual_dividend_yield"] == pytest.approx(0.06)
    assert metrics["consecutive_years"] == 2


def test_financials_only_return_reports_disclosed_as_of_date():
    statements = pd.DataFrame(
        {
            "code": ["000001"] * 4,
            "report_period": ["2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31"],
            "available_at": ["2022-03-01", "2023-03-01", "2024-03-01", "2025-03-01"],
            "operating_cash_flow": [10, 12, 15, 18],
            "capex": [2, 3, 4, 5],
            "net_income": [5, 6, 7, 8],
        }
    )
    as_of = financials_as_of(statements, "000001", "2024-06-01")
    metrics = quality_metrics_as_of(statements, "000001", "2024-06-01")

    assert len(as_of) == 3
    assert as_of["report_period"].max() == pd.Timestamp("2023-12-31")
    assert metrics["free_cash_flow"] == 11


def test_baostock_lifecycle_uses_implementation_announcement_conservatively():
    raw = pd.DataFrame(
        {
            "plan_announce_date": ["2024-03-01"],
            "agm_date": ["2024-04-01"],
            "implement_announce_date": ["2024-05-01"],
            "ex_date": ["2024-05-10"],
            "pay_date": ["2024-05-10"],
            "cash_per_share": [0.5],
        }
    )
    eligible, _ = normalize_dividend_events(normalize_baostock_dividends(raw, "000001"))

    before = dividend_metrics_as_of(eligible, "000001", "2024-04-30", close=10)
    after = dividend_metrics_as_of(eligible, "000001", "2024-05-10", close=10)

    assert before["annual_dividend_yield"] == 0
    assert after["annual_dividend_yield"] == pytest.approx(0.05)


def test_implemented_ttm_only_enters_on_ex_date_and_rolls_out_after_365_days():
    events = pd.DataFrame(
        [
            ["000001", 2023, "old", "2023-08-01", "2023-08-10", 0.5, "年度", "已实施"],
            ["000001", 2024, "new", "2024-01-01", "2024-08-10", 0.6, "年度", "已实施"],
        ],
        columns=["code", "report_year", "plan_id", "public_date", "ex_date", "cash_per_share", "plan_type", "status"],
    )
    eligible, _ = normalize_dividend_events(events)

    before_ex = dividend_metrics_as_of(eligible, "000001", "2024-08-09", close=10)
    on_ex = dividend_metrics_as_of(eligible, "000001", "2024-08-10", close=10)
    after_roll = dividend_metrics_as_of(eligible, "000001", "2024-08-11", close=10)

    assert before_ex["implemented_ttm_yield"] == pytest.approx(0.05)
    assert on_ex["implemented_ttm_yield"] == pytest.approx(0.06)
    assert after_roll["implemented_ttm_yield"] == pytest.approx(0.06)


def test_stage_audit_does_not_backfill_final_cash_to_plan_stage():
    events = pd.DataFrame(
        [
            ["000001", 2024, "x", "2024-03-01", "2024-08-10", 0.6, "年度", "已实施", "2024-03-01"],
        ],
        columns=[
            "code",
            "report_year",
            "plan_id",
            "public_date",
            "ex_date",
            "cash_per_share",
            "plan_type",
            "status",
            "plan_announce_date",
        ],
    )
    prices = pd.DataFrame({"date": ["2024-04-01"], "close": [10.0]})
    audit, metrics = audit_dividend_stages(events, prices, "000001", "2024-04-01")

    assert metrics["implemented_ttm_yield"] == 0
    assert audit.iloc[0]["stage_audit_reason"] == "future_final_cash_not_backfilled"
