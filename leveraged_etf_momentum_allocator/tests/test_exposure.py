"""Paper exposure construction tests."""
from __future__ import annotations

from exposure import target_weight_for_beta


def test_tqqq_half_weight_for_1_5_beta():
    pos = target_weight_for_beta("TQQQ", target_underlying_beta=1.5)
    assert abs(pos["weights"]["TQQQ"] - 0.5) < 1e-9
    assert abs(pos["weights"]["BSV"] - 0.5) < 1e-9
    assert abs(pos["implied_underlying_beta"] - 1.5) < 1e-9


def test_tecs_half_weight_inverse():
    pos = target_weight_for_beta("TECS", target_underlying_beta=1.5)
    assert abs(pos["weights"]["TECS"] - 0.5) < 1e-9
    assert abs(pos["implied_underlying_beta"] - (-1.5)) < 1e-9


def test_uvxy_cap_overlay():
    pos = target_weight_for_beta("UVXY", uvxy_max_weight=0.25)
    assert pos["weights"]["UVXY"] == 0.25
    assert pos["overlay"] == "PAPER_EXECUTION_OVERLAY"


def test_not_one_point_five_portfolio_leverage():
    """Guard against confusing 1.5x beta with 150% ETF weight."""
    pos = target_weight_for_beta("TQQQ", target_underlying_beta=1.5)
    assert pos["weights"]["TQQQ"] < 1.0
    assert pos["weights"]["TQQQ"] != 1.5
