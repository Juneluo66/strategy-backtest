"""Tests for explicit margin absence reason codes."""
from __future__ import annotations

import numpy as np
import pandas as pd

from etf_rotation.factors import classify_missing_reasons
from etf_rotation.non_ohlcv.absence import (
    classify_download_error_message,
    load_margin_absence_kinds,
)


def test_classify_download_error_message():
    assert classify_download_error_message("Response ended prematurely") == "request_failed"
    assert classify_download_error_message("返回数据为空") == "source_no_record"
    assert classify_download_error_message("invalid code mapping") == "symbol_mapping_failure"


def test_known_codes_not_blanket_download_failure(tmp_path):
    err = tmp_path / "download_errors.csv"
    err.write_text(
        "code,field,error\n"
        "159985,eastmoney_margin,返回数据为空\n"
        "518880,eastmoney_margin,Response ended prematurely\n",
        encoding="utf-8",
    )
    kinds = load_margin_absence_kinds(tmp_path)
    assert kinds["159985"] == "not_margin_eligible"
    assert kinds["518880"] == "request_failed"
    assert "download_failure" not in kinds.values()


def test_classify_missing_reasons_uses_kinds():
    dates = pd.date_range("2020-01-01", periods=5, freq="B")
    panel = pd.DataFrame({
        "date": list(dates) * 2,
        "code": ["159985"] * 5 + ["510300"] * 5,
        "MARGIN_BUY_RATIO": [np.nan] * 5 + [0.1] * 5,
    })
    reasons = classify_missing_reasons(
        panel,
        "MARGIN_BUY_RATIO",
        listing_dates={"159985": dates[0], "510300": dates[0]},
        margin_absence_kinds={"159985": "not_margin_eligible"},
    )
    assert (reasons.loc[panel.code.eq("159985")] == "not_margin_eligible").all()
    assert (reasons.loc[panel.code.eq("510300")] == "observed").all()
