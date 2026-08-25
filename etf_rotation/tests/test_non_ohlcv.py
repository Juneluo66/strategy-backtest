"""Guards for non-OHLCV PIT handling: no lookahead, no zero-fill, partial stays partial."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from etf_rotation.factors import cross_sectional_scores
from etf_rotation.non_ohlcv.compute import (
    margin_buy_ratio,
    margin_change,
    panel_from_observations,
    share_change,
)
from etf_rotation.non_ohlcv.margin import normalize_margin_detail
from etf_rotation.non_ohlcv.schema import pit_values, validate_observations
from etf_rotation.non_ohlcv.shares import share_source_status


def _obs(rows: list[dict]) -> pd.DataFrame:
    base = datetime.now(timezone.utc)
    frame = pd.DataFrame(rows)
    frame["source"] = "unit_test"
    frame["source_version"] = "test_v1"
    frame["retrieved_at"] = base
    return validate_observations(frame)


def test_available_at_cannot_precede_observation_date() -> None:
    with pytest.raises(ValueError, match="available_at"):
        _obs([{
            "code": "510300",
            "observation_date": "2024-01-02",
            "available_at": "2024-01-01",
            "value": 1.0,
        }])


def test_pit_excludes_future_observations() -> None:
    observations = _obs([
        {
            "code": "510300",
            "observation_date": "2024-01-02",
            "available_at": "2024-01-03",
            "value": 100.0,
        },
        {
            "code": "510300",
            "observation_date": "2024-01-04",
            "available_at": "2024-01-05",
            "value": 110.0,
        },
    ])
    visible = pit_values(observations, pd.Series(["2024-01-04"]))
    assert set(visible["value"]) == {100.0}


def test_panel_does_not_lookahead_or_zero_fill_absent_codes() -> None:
    observations = _obs([
        {
            "code": "510300",
            "observation_date": "2024-01-02",
            "available_at": "2024-01-03",
            "value": 50.0,
        },
    ])
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    panel = panel_from_observations(observations, dates, ["510300", "159915"])
    assert pd.isna(panel.loc[dates[0], "510300"])
    assert panel.loc[dates[1], "510300"] == 50.0
    assert panel["159915"].isna().all()
    assert not (panel.fillna(0).eq(0) & panel.notna()).any().any()


def test_share_and_margin_changes_preserve_nan() -> None:
    dates = pd.date_range("2024-01-01", periods=12, freq="B")
    share = pd.DataFrame(
        {"510300": [np.nan] * 5 + [1.0, 1.1, 1.2, 1.0, 0.0, 1.3, 1.4]}, index=dates
    )
    chg1 = share_change(share, 1)
    assert pd.isna(chg1.iloc[0]["510300"])
    # prior share exactly 0 → NaN, never a finite fake change
    assert pd.isna(chg1.loc[dates[10], "510300"])
    rzye = pd.DataFrame({"510300": [np.nan, 10.0] + [np.nan] * 10}, index=dates)
    chg = margin_change(rzye, 1)
    assert pd.isna(chg.iloc[0, 0])
    assert pd.isna(chg.iloc[2, 0])


def test_margin_buy_ratio_missing_turnover_is_nan() -> None:
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    rzmre = pd.DataFrame({"510300": [1.0, 2.0, 3.0]}, index=idx)
    close = pd.DataFrame({"510300": [10.0, 10.0, 10.0]}, index=idx)
    volume = pd.DataFrame({"510300": [100.0, 0.0, np.nan]}, index=idx)
    ratio = margin_buy_ratio(rzmre, close, volume)
    assert ratio.iloc[0, 0] == pytest.approx(0.001)
    assert pd.isna(ratio.iloc[1, 0])
    assert pd.isna(ratio.iloc[2, 0])


def test_normalize_margin_does_not_invent_absent_securities() -> None:
    raw = pd.DataFrame({
        "标的证券代码": ["510300"],
        "信用交易日期": ["2024-01-02"],
        "融资余额": [1_000_000.0],
        "融资买入额": [50_000.0],
    })
    normalized = normalize_margin_detail(
        raw, exchange="SSE", available_at=pd.Timestamp("2024-01-03"), source_version="probe"
    )
    assert set(normalized["code"]) == {"510300"}
    assert "159915" not in set(normalized["code"])


def test_share_source_blocked_without_token() -> None:
    status = share_source_status(tushare_token=None)
    assert status.ready is False
    assert "partial" in status.reason.lower() or "TUSHARE" in status.reason


def test_partial_factor_set_propagates_when_non_ohlcv_missing() -> None:
    dates = pd.date_range("2024-01-01", periods=5, freq="B")
    panel = pd.DataFrame({
        "date": np.repeat(dates, 2),
        "code": ["510300", "159915"] * 5,
        "ADX_14D": np.linspace(0.1, 0.5, 10),
        "MARGIN_BUY_RATIO": np.nan,
    })
    with pytest.raises(Exception):
        cross_sectional_scores(panel, ["ADX_14D", "MARGIN_BUY_RATIO"], [1, -1], [1, 1], run_mode="research")
    scored, audit = cross_sectional_scores(panel, ["ADX_14D"], [1], [1], run_mode="baseline")
    assert audit.reproduction_status == "BASELINE_OHLCV"
