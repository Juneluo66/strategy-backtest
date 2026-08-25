"""Frozen EW9 equal-weight rules."""
from __future__ import annotations

import pandas as pd

from us_sector_equal_weight.config import FIXED_SECTORS, load_config
from us_sector_equal_weight.schedules import (
    VERSION_FREQ,
    build_ew_targets,
    equal_weight_series,
)


def test_universe_frozen_nine():
    cfg = load_config()
    assert cfg.sectors == FIXED_SECTORS
    assert cfg.versions == list(VERSION_FREQ)


def test_equal_weights_sum_to_one():
    w = equal_weight_series()
    assert abs(w.sum() - 1.0) < 1e-12
    assert (w - 1.0 / 9.0).abs().max() < 1e-12


def test_targets_never_rank_or_tilt():
    idx = pd.bdate_range("2010-01-01", periods=400)
    closes = pd.DataFrame({s: range(len(idx)) for s in FIXED_SECTORS}, index=idx, dtype=float)
    for freq in ("monthly", "quarterly", "annual"):
        targets = build_ew_targets(closes, frequency=freq)
        assert targets
        for w in targets.values():
            assert abs(w.sum() - 1.0) < 1e-12
            assert (w - 1.0 / 9.0).abs().max() < 1e-12


def test_forbidden_flags_in_config():
    cfg = load_config()
    assert cfg.raw.get("sector_ranking") is False
    assert cfg.raw.get("trend_filter") is False
    assert cfg.raw.get("sma_filter") is False
    assert cfg.raw.get("bil_sleeve") is False
    assert cfg.raw.get("ibkr_modified") is False
