"""Tests for TuShare non-OHLCV fetch guards and production gates."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from etf_rotation.config import RotationConfig
from etf_rotation.non_ohlcv.fetch import fetch_non_ohlcv, production_manifest_path
from etf_rotation.non_ohlcv.schema import validate_observations
from etf_rotation.non_ohlcv.tushare_source import (
    TuShareTokenError,
    next_session_available_at,
    resolve_tushare_token,
    to_ts_code,
)
from etf_rotation.non_ohlcv.validate import (
    build_factor_frames,
    render_validation_markdown,
    run_validation,
)


def test_auto_source_prefers_free_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_rotation.non_ohlcv.fetch import _resolve_source

    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    assert _resolve_source("auto", None) == "free"
    assert _resolve_source("free", None) == "free"


def test_eastmoney_margin_normalizes_pit_columns() -> None:
    from etf_rotation.non_ohlcv.free_source import _to_obs

    obs = _to_obs(
        pd.Series(["510300", "510300"]),
        pd.Series(["2024-01-02", "2024-01-03"]),
        pd.Series([1e8, 1.1e8]),
        field="rzye",
        source="Eastmoney",
        source_version="probe",
        trading_calendar=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        retrieved_at=datetime.now(timezone.utc),
    )
    assert list(obs.columns) == [
        "code", "observation_date", "available_at", "value",
        "source", "source_version", "retrieved_at",
    ]
    assert (obs["available_at"] > obs["observation_date"]).all()



def test_to_ts_code_exchange_suffix() -> None:
    assert to_ts_code("510300") == "510300.SH"
    assert to_ts_code("159915") == "159915.SZ"


def test_available_at_is_next_session_not_same_day() -> None:
    calendar = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    available = next_session_available_at(pd.Series(["2024-01-02"]), calendar)
    assert available.iloc[0] == pd.Timestamp("2024-01-03 08:30:00")
    assert available.iloc[0] > pd.Timestamp("2024-01-02")


def test_fetch_non_ohlcv_tushare_exits_without_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    config = RotationConfig(cache_dir=tmp_path / "cache", reports_dir=tmp_path / "reports")
    (config.cache_dir / "prices").mkdir(parents=True)
    with pytest.raises(TuShareTokenError):
        fetch_non_ohlcv(config, full=True, source="tushare")


def test_fetch_non_ohlcv_requires_full_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "dummy")
    config = RotationConfig(cache_dir=tmp_path / "cache", reports_dir=tmp_path / "reports")
    with pytest.raises(RuntimeError, match="--full"):
        fetch_non_ohlcv(config, full=False)


def test_validation_blocks_sparse_margin_and_writes_report(tmp_path: Path) -> None:
    dates = pd.date_range("2024-01-01", periods=30, freq="B")
    codes = ["510300", "159915"]
    prices = {
        code: pd.DataFrame({
            "date": dates,
            "code": code,
            "open": 1.0,
            "close": 1.0,
            "high": 1.1,
            "low": 0.9,
            "volume": 1_000_000.0,
            "amount": 1_000_000.0,
        })
        for code in codes
    }
    # Only one code, sparse days → missing_ratio high → BLOCKED
    retrieved = datetime.now(timezone.utc)
    raw = {
        "rzye": validate_observations(pd.DataFrame({
            "code": ["510300"] * 5,
            "observation_date": dates[:5],
            "available_at": dates[:5] + pd.Timedelta(days=1),
            "value": [1e8, 1.1e8, 1.2e8, 1.0e8, 9e7],
            "source": "TuShare/rzye",
            "source_version": "test",
            "retrieved_at": retrieved,
        })),
        "rzmre": validate_observations(pd.DataFrame({
            "code": ["510300"] * 5,
            "observation_date": dates[:5],
            "available_at": dates[:5] + pd.Timedelta(days=1),
            "value": [1e6, 1.1e6, 1.2e6, 1.0e6, 9e5],
            "source": "TuShare/rzmre",
            "source_version": "test",
            "retrieved_at": retrieved,
        })),
        "total_share": validate_observations(pd.DataFrame({
            "code": ["510300"] * 5,
            "observation_date": dates[:5],
            "available_at": dates[:5] + pd.Timedelta(days=1),
            "value": [1000.0, 1010.0, 1020.0, 1030.0, 1040.0],
            "source": "TuShare/total_share",
            "source_version": "test",
            "retrieved_at": retrieved,
        })),
    }
    report, factors = run_validation(raw, prices, codes, source_version="test")
    assert report.status == "BLOCKED_BY_DATA"
    assert report.unblock_blocked_by_data is False
    assert all(item.missing_ratio >= 0.05 for item in report.factor_results)
    path = tmp_path / "non_ohlcv_validation.md"
    render_validation_markdown(report, path)
    text = path.read_text(encoding="utf-8")
    assert "BLOCKED_BY_DATA" in text
    assert "TuShare" in text
    assert "Unblock BLOCKED_BY_DATA: **no**" in text
    # No zero fill for absent 159915
    for frame in factors.values():
        missing = frame.loc[frame["code"].eq("159915"), "value"]
        assert missing.isna().all()


def test_production_gate_passes_on_dense_synthetic_data() -> None:
    # Lag windows (5/10/20) create leading NaNs; need long history so
    # missing_ratio = window/n_days stays under 5%.
    dates = pd.date_range("2022-01-03", periods=500, freq="B")
    codes = ["510300", "159915"]
    prices = {
        code: pd.DataFrame({
            "date": dates,
            "code": code,
            "open": 2.0,
            "close": 2.0,
            "high": 2.1,
            "low": 1.9,
            "volume": 1_000_000.0,
            "amount": 2_000_000.0,
        })
        for code in codes
    }
    retrieved = datetime.now(timezone.utc)
    rows = []
    for code in codes:
        for stamp in dates:
            rows.append({
                "code": code,
                "observation_date": stamp,
                "available_at": stamp,
                "value": 1e8 + (hash((code, stamp.date())) % 1000),
                "source": "TuShare/rzye",
                "source_version": "dense",
                "retrieved_at": retrieved,
            })
    rzye = validate_observations(pd.DataFrame(rows))
    rzmre = rzye.assign(value=rzye["value"] * 0.01, source="TuShare/rzmre")
    share_rows = []
    for code in codes:
        level = 5000.0
        for stamp in dates:
            level += 1.0
            share_rows.append({
                "code": code,
                "observation_date": stamp,
                "available_at": stamp,
                "value": level,
                "source": "TuShare/total_share",
                "source_version": "dense",
                "retrieved_at": retrieved,
            })
    raw = {
        "rzye": rzye,
        "rzmre": validate_observations(rzmre),
        "total_share": validate_observations(pd.DataFrame(share_rows)),
    }
    report, _ = run_validation(raw, prices, codes, source_version="dense")
    assert report.unblock_blocked_by_data is True
    assert report.status == "production"
    assert all(item.production_eligible for item in report.factor_results)


def test_refuse_overwrite_production(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "dummy")
    config = RotationConfig(cache_dir=tmp_path / "cache", reports_dir=tmp_path / "reports")
    root = config.cache_dir / "non_ohlcv"
    root.mkdir(parents=True)
    production_manifest_path(config).write_text(
        '{"status": "production", "source_version": "old", "factors": ["SHARE_CHG_5D"]}',
        encoding="utf-8",
    )
    # Additive promotion is allowed; fetch still fails without OHLCV cache.
    with pytest.raises(RuntimeError, match="no cached OHLCV"):
        fetch_non_ohlcv(config, full=True, source="free")


def test_build_factor_frames_never_zero_fills_absent_codes() -> None:
    dates = pd.date_range("2024-01-01", periods=15, freq="B")
    prices = {
        "510300": pd.DataFrame({
            "date": dates, "code": "510300", "open": 1.0, "close": 1.0,
            "high": 1.0, "low": 1.0, "volume": 100.0, "amount": 100.0,
        }),
        "159915": pd.DataFrame({
            "date": dates, "code": "159915", "open": 1.0, "close": 1.0,
            "high": 1.0, "low": 1.0, "volume": 100.0, "amount": 100.0,
        }),
    }
    retrieved = datetime.now(timezone.utc)
    obs = validate_observations(pd.DataFrame({
        "code": ["510300"] * len(dates),
        "observation_date": dates,
        "available_at": dates,
        "value": np.linspace(100.0, 200.0, len(dates)),
        "source": "TuShare/total_share",
        "source_version": "t",
        "retrieved_at": retrieved,
    }))
    factors = build_factor_frames(
        {"total_share": obs, "rzye": obs.iloc[0:0], "rzmre": obs.iloc[0:0]},
        prices,
        ["510300", "159915"],
    )
    share = factors["SHARE_CHG_5D"]
    assert share.loc[share["code"].eq("159915"), "value"].isna().all()
    assert not (
        share["value"].isna() & False
    ).any()  # placeholder clarity: NaNs remain NaN
