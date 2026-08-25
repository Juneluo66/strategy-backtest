"""Stateful Top-N selection, Exp4-style hysteresis, and volatility gate."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from etf_rotation.config import RotationConfig


@dataclass
class PortfolioState:
    holdings: list[str] = field(default_factory=list)
    holding_days: dict[str, int] = field(default_factory=dict)


def rebalance_dates(dates: pd.DatetimeIndex, frequency: int) -> pd.DatetimeIndex:
    return dates.sort_values()[::frequency]


def choose_holdings(day: pd.DataFrame, state: PortfolioState, config: RotationConfig) -> tuple[list[str], list[dict]]:
    """Replace at most one holding only if rank benefit and age meet the sealed rule."""
    ranked = day.dropna(subset=["score", "rank01"]).sort_values("score", ascending=False)
    candidates = ranked["code"].astype(str).tolist()
    if not state.holdings:
        selected = candidates[:config.position_size]
        return selected, [{"action": "initial_buy", "code": code} for code in selected]
    current = [code for code in state.holdings if code in set(candidates)]
    if not config.use_hysteresis:
        selected = candidates[:config.position_size]
        return selected, [{"action": "replace", "code": code} for code in set(selected).symmetric_difference(current)]
    if len(current) < config.position_size:
        additions = [code for code in candidates if code not in current][:config.position_size - len(current)]
        return current + additions, [{"action": "buy", "code": code} for code in additions]
    ranks = ranked.set_index("code")["rank01"]
    selected, actions = list(current), []
    entrants = [code for code in candidates if code not in selected]
    for weakest in sorted(selected, key=lambda code: ranks.get(code, -np.inf)):
        if len(actions) // 2 >= config.max_replacements or not entrants:
            break
        entrant = entrants.pop(0)
        benefit = float(ranks[entrant] - ranks.get(weakest, 0.0))
        old_enough = state.holding_days.get(weakest, 0) >= config.min_hold_days
        if benefit >= config.delta_rank and old_enough:
            selected[selected.index(weakest)] = entrant
            actions.extend([
                {"action": "sell", "code": weakest, "rank_benefit": benefit},
                {"action": "buy", "code": entrant, "rank_benefit": benefit},
            ])
    return selected, actions


def volatility_exposure(proxy_prices: pd.DataFrame, config: RotationConfig) -> pd.Series:
    """Use trailing volatility percentile shifted one day to prevent look-ahead."""
    close = proxy_prices.sort_values("date").set_index("date")["close"]
    vol = close.pct_change().rolling(config.regime_window).std()
    percentile = vol.expanding(min_periods=config.regime_window * 2).rank(pct=True).shift(1) * 100
    bins = list(config.regime_thresholds)
    exposures = list(config.regime_exposures)
    values = np.select(
        [percentile <= bins[0], percentile <= bins[1], percentile <= bins[2]],
        exposures[:-1], default=exposures[-1],
    )
    return pd.Series(values, index=close.index, name="exposure").where(percentile.notna(), exposures[0])
