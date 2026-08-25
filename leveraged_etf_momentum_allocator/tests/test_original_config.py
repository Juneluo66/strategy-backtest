"""Tests for original config verification."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config import ProjectConfig


def test_source_verified():
    cfg = ProjectConfig.load(ROOT)
    assert cfg.is_original_verified()
    assert cfg.is_frozen()


def test_universe_exact():
    cfg = ProjectConfig.load(ROOT)
    assert cfg.universe() == [
        "SPY", "QQQ", "TQQQ", "UVXY", "TECL", "SPXL", "SQQQ", "TECS", "BSV"
    ]


def test_parameters_frozen():
    cfg = ProjectConfig.load(ROOT)
    p = cfg.parameters()
    assert p["rsi_period"] == 10
    assert p["spy_sma_period"] == 200
