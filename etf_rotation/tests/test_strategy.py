from __future__ import annotations

from dataclasses import replace

import pandas as pd

from etf_rotation.config import frozen_config
from etf_rotation.strategy import PortfolioState, choose_holdings, volatility_exposure


def _day(entrant_rank: float) -> pd.DataFrame:
    return pd.DataFrame(
        {"code": ["A", "B", "C"], "score": [0.9, 0.5, 1.0], "rank01": [0.9, 0.5, entrant_rank]}
    )


def test_hysteresis_does_not_replace_for_small_benefit() -> None:
    config = frozen_config(lookback=20)
    state = PortfolioState(["A", "B"], {"A": 12, "B": 12})
    selected, actions = choose_holdings(_day(0.54), state, config)
    assert selected == ["A", "B"]
    assert actions == []


def test_hysteresis_replaces_one_old_holding() -> None:
    config = frozen_config(lookback=20)
    state = PortfolioState(["A", "B"], {"A": 12, "B": 12})
    selected, actions = choose_holdings(_day(0.65), state, config)
    assert set(selected) == {"A", "C"}
    assert [action["action"] for action in actions] == ["sell", "buy"]


def test_hysteresis_respects_minimum_holding_days() -> None:
    config = frozen_config(lookback=20)
    state = PortfolioState(["A", "B"], {"A": 12, "B": 8})
    selected, actions = choose_holdings(_day(0.8), state, config)
    assert selected == ["A", "B"]
    assert actions == []


def test_hysteresis_can_replace_more_than_one_when_explicitly_enabled() -> None:
    config = replace(frozen_config(lookback=20), max_replacements=2)
    state = PortfolioState(["A", "B"], {"A": 12, "B": 12})
    selected, actions = choose_holdings(
        pd.DataFrame({"code": ["A", "B", "C", "D"], "score": [0.1, 0.2, 0.9, 1.0],
                      "rank01": [0.1, 0.2, 0.9, 1.0]}),
        state,
        config,
    )
    assert set(selected) == {"C", "D"}
    assert len(actions) == 4


def test_regime_gate_steps_down_in_high_volatility() -> None:
    prices = pd.DataFrame(
        {"date": pd.date_range("2020-01-01", periods=100, freq="B"),
         "close": [100 + (i % 2) * (0.1 if i < 60 else 10) for i in range(100)]}
    )
    exposure = volatility_exposure(prices, frozen_config(lookback=20))
    assert exposure.iloc[-1] in {0.7, 0.4, 0.1}
