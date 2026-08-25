"""Tests for non-OHLCV runtime wiring and run-mode gates."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from etf_rotation.config import RotationConfig
from etf_rotation.factors import (
    FactorAvailabilityError,
    cross_sectional_scores,
    factor_panel,
)
from etf_rotation.non_ohlcv.loader import (
    TIER_PRODUCTION,
    TIER_RESEARCH_STAGING,
    FactorSource,
    merge_factor_into_panel,
)
from etf_rotation.non_ohlcv.validate import validate_factors


def _prices(n: int = 80) -> dict[str, pd.DataFrame]:
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    out = {}
    for i, code in enumerate(["510300", "159915", "512480"]):
        close = 100 + i + np.arange(n) * 0.05
        out[code] = pd.DataFrame({
            "date": dates, "code": code, "open": close * 0.999, "close": close,
            "high": close * 1.01, "low": close * 0.99, "amount": 1e8, "volume": 1e6,
        })
    return out


def _staging_share(tmp_path: Path, prices: dict[str, pd.DataFrame]) -> Path:
    rows = []
    for code, frame in prices.items():
        dates = pd.to_datetime(frame["date"])
        level = 1000.0
        for stamp in dates:
            level += 1.0
            rows.append({
                "date": stamp, "code": code, "value": (level - 1000.0) / 1000.0,
                "observation_date": stamp, "available_at": stamp,
                "source": "test", "source_version": "t", "retrieved_at": datetime.now(timezone.utc),
            })
    staging = tmp_path / "cache" / "non_ohlcv" / "staging" / "test_v1"
    staging.mkdir(parents=True)
    for name in ("SHARE_CHG_5D", "SHARE_CHG_20D", "MARGIN_BUY_RATIO", "MARGIN_CHG_10D"):
        frame = pd.DataFrame(rows)
        if name.startswith("MARGIN"):
            # Leave one code structurally missing (NaN) — never zero-fill.
            frame.loc[frame["code"].eq("512480"), "value"] = np.nan
        frame.to_parquet(staging / f"{name}.parquet", index=False)
    return staging


def test_staging_enters_scoring_without_zero_fill(tmp_path: Path) -> None:
    prices = _prices()
    _staging_share(tmp_path, prices)
    config = RotationConfig(cache_dir=tmp_path / "cache", reports_dir=tmp_path / "reports")
    panel = factor_panel(prices, config)
    assert "SHARE_CHG_5D" in panel.columns
    assert panel["SHARE_CHG_5D"].notna().any()
    assert panel.loc[panel.code.eq("512480"), "MARGIN_BUY_RATIO"].isna().all()
    # No accidental zeros for missing margin cells
    margin = panel["MARGIN_BUY_RATIO"]
    assert not ((margin == 0) & panel.code.eq("512480")).any()

    for factor in ("SHARE_CHG_5D", "SHARE_CHG_20D", "MARGIN_BUY_RATIO", "MARGIN_CHG_10D"):
        panel[f"_tier_{factor}"] = TIER_RESEARCH_STAGING
    scored, audit = cross_sectional_scores(
        panel, ["MOM_20D", "SHARE_CHG_5D"], [1, -1], [1, 1], run_mode="research", sources={}
    )
    assert audit.reproduction_status == "PARTIAL_REPRODUCTION"
    assert "SHARE_CHG_5D" in audit.actual_factors
    assert scored["z_SHARE_CHG_5D"].notna().any()
    assert list(audit.declared_factors) == list(audit.actual_factors)


def test_strict_blocks_staging_degradation(tmp_path: Path) -> None:
    prices = _prices()
    _staging_share(tmp_path, prices)
    config = RotationConfig(cache_dir=tmp_path / "cache", reports_dir=tmp_path / "reports")
    panel = factor_panel(prices, config)
    for factor in ("SHARE_CHG_5D", "SHARE_CHG_20D", "MARGIN_BUY_RATIO", "MARGIN_CHG_10D"):
        panel[f"_tier_{factor}"] = TIER_RESEARCH_STAGING
    with pytest.raises(FactorAvailabilityError, match="strict mode"):
        cross_sectional_scores(
            panel,
            ["MOM_20D", "ADX_14D", "MARGIN_BUY_RATIO", "SHARE_CHG_5D"],
            [1, 1, -1, -1],
            [1, 1, 1, 1],
            run_mode="strict",
            sources={},
        )


def test_research_marks_partial_and_baseline_refuses_c1(tmp_path: Path) -> None:
    prices = _prices()
    _staging_share(tmp_path, prices)
    config = RotationConfig(cache_dir=tmp_path / "cache", reports_dir=tmp_path / "reports")
    panel = factor_panel(prices, config)
    for factor in ("SHARE_CHG_5D", "SHARE_CHG_20D", "MARGIN_BUY_RATIO", "MARGIN_CHG_10D"):
        panel[f"_tier_{factor}"] = TIER_RESEARCH_STAGING
    scored, audit = cross_sectional_scores(
        panel,
        ["MOM_20D", "ADX_14D", "MARGIN_BUY_RATIO", "SHARE_CHG_5D"],
        [1, 1, -1, -1],
        [1, 1, 1, 1],
        run_mode="research",
        sources={},
    )
    assert audit.reproduction_status == "PARTIAL_REPRODUCTION"
    assert scored["is_partial_factor_set"].all()
    with pytest.raises(FactorAvailabilityError, match="baseline mode refuses"):
        cross_sectional_scores(
            panel,
            ["ADX_14D", "MARGIN_BUY_RATIO"],
            [1, -1],
            [1, 1],
            run_mode="baseline",
            sources={},
        )


def test_merge_never_zero_fills_missing() -> None:
    panel = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-01", "2020-01-02"]),
        "code": ["510300", "159915"],
        "MOM_20D": [0.1, 0.2],
    })
    source = FactorSource(
        "SHARE_CHG_5D",
        TIER_RESEARCH_STAGING,
        None,
        pd.DataFrame({
            "date": pd.to_datetime(["2020-01-01"]),
            "code": ["510300"],
            "value": [0.05],
        }),
    )
    merged = merge_factor_into_panel(panel, source)
    assert merged.loc[merged.code.eq("510300"), "SHARE_CHG_5D"].iloc[0] == pytest.approx(0.05)
    assert pd.isna(merged.loc[merged.code.eq("159915"), "SHARE_CHG_5D"].iloc[0])


def test_share_chg_20d_eligible_grid_can_pass_while_full_grid_kept() -> None:
    dates = pd.date_range("2020-01-01", periods=60, freq="B")
    rows = []
    for code in ("510300", "159915"):
        for i, stamp in enumerate(dates):
            value = 0.01 if i >= 20 else np.nan
            rows.append({
                "date": stamp, "code": code, "value": value,
                "available_at": stamp, "observation_date": stamp,
            })
    frame = pd.DataFrame(rows)
    # Pad early calendar noise on full grid by prepending pre-listing-like empties already NaN
    results = validate_factors({"SHARE_CHG_20D": frame, "SHARE_CHG_5D": frame.assign(value=0.01),
                                "MARGIN_BUY_RATIO": frame.assign(value=np.nan),
                                "MARGIN_CHG_10D": frame.assign(value=np.nan)})
    by_name = {item.factor: item for item in results}
    assert by_name["SHARE_CHG_20D"].missing_ratio_full_grid > by_name["SHARE_CHG_20D"].missing_ratio_eligible_grid
    # Eligible after warmup should be near zero missing
    assert by_name["SHARE_CHG_20D"].missing_ratio_eligible_grid < 0.05
    assert by_name["SHARE_CHG_20D"].production_eligible is True
    # Margin still fails without shrinking
    assert by_name["MARGIN_BUY_RATIO"].production_eligible is False
