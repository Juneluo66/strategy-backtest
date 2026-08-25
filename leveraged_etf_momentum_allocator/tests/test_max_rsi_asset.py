"""GetMaxRsiAsset tests."""
from __future__ import annotations

from original_strategy import get_max_rsi_asset


def test_tecs_higher():
    t, path = get_max_rsi_asset(60, 40)
    assert t == "TECS"
    assert "TECS" in path


def test_bsv_higher():
    t, _ = get_max_rsi_asset(40, 60)
    assert t == "BSV"


def test_tie_goes_to_tecs():
    t, _ = get_max_rsi_asset(50, 50)
    assert t == "TECS"
