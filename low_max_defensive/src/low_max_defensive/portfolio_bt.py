"""Equal-weight / high-MAX-exclusion / low-MAX long-only simulator.

Trading clock, costs, and membership handling match max_effect_vix:
signal at prior month-end close; fill at next session open; index exits liquidated.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pandas as pd

from max_effect_vix.factors import max_factor, monthly_signal_dates
from max_effect_vix.portfolio import equal_weights, select_low_max
from max_effect_vix.status import DELISTING_RETURN_UNAVAILABLE, INDEX_EXIT

MembershipFn = Callable[[pd.Timestamp], frozenset[str]]


def select_exclude_high_max(factor: pd.Series, exclude_frac: float) -> list[str]:
    """Keep all eligible names except the highest-MAX exclude_frac (pre-specified grid)."""
    valid = factor.dropna().sort_values(ascending=False, kind="stable")
    if valid.empty:
        return []
    n_drop = int(np.floor(len(valid) * exclude_frac))
    keep = valid.iloc[n_drop:]
    return keep.index.tolist()


def run_portfolio(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    *,
    mode: str,
    lookback: int = 21,
    top_returns: int = 5,
    min_dollar_volume: float = 5_000_000,
    one_way_bps: float = 5.0,
    membership_on: Optional[MembershipFn] = None,
    exclude_frac: float = 0.0,
    portfolio_decile: float = 0.10,
    max_portfolio_size: int = 25,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    mode:
      - ew: equal-weight all eligible members
      - exclude_high: drop top exclude_frac by MAX, EW remainder
      - low_max: frozen low-MAX long-only (decile + cap)
    """
    common = opens.index.intersection(closes.index).intersection(volumes.index)
    opens, closes, volumes = (frame.reindex(common).sort_index() for frame in (opens, closes, volumes))
    returns = closes.pct_change(fill_method=None)
    factors = returns.apply(max_factor, lookback=lookback, top_returns=top_returns)
    dollar_volume = (closes * volumes).rolling(lookback, min_periods=lookback).mean()
    signal_dates = set(monthly_signal_dates(common))
    ordered = list(common)
    execute_map: dict[pd.Timestamp, pd.Timestamp] = {}
    for signal_date in monthly_signal_dates(common):
        pos = ordered.index(signal_date)
        if pos + 1 < len(ordered):
            execute_map[ordered[pos + 1]] = signal_date

    weights = pd.Series(dtype=float)
    pending_target: Optional[pd.Series] = None
    pending_signal: Optional[pd.Timestamp] = None
    pending_meta: dict = {}
    rows: list[dict] = []
    holdings: list[dict] = []
    trades: list[dict] = []
    exit_events: list[dict] = []
    previous_close = None

    for date in common:
        open_prices = opens.loc[date]
        close_prices = closes.loc[date]
        gross_return = 0.0
        cost = 0.0

        if previous_close is not None and not weights.empty:
            overnight = (open_prices / previous_close - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            gross_return += float((weights.reindex(overnight.index, fill_value=0.0) * overnight).sum())

        if membership_on is not None and not weights.empty:
            members = membership_on(date)
            exited = [symbol for symbol in weights.index if symbol not in members]
            if exited:
                for symbol in exited:
                    exit_events.append(
                        {
                            "date": date,
                            "symbol": symbol,
                            "event": INDEX_EXIT,
                            "reason": "removed_from_sp500",
                            "delisting_return_status": DELISTING_RETURN_UNAVAILABLE,
                            "weight_before_exit": float(weights[symbol]),
                        }
                    )
                liquidated = float(weights.loc[exited].abs().sum())
                cost += liquidated * one_way_bps / 10_000
                trades.append(
                    {
                        "date": date,
                        "turnover": liquidated,
                        "cost": liquidated * one_way_bps / 10_000,
                        "holdings": int(len(weights) - len(exited)),
                        "reason": INDEX_EXIT,
                    }
                )
                weights = weights.drop(labels=exited)

        if date in execute_map and pending_target is not None:
            turnover = float(pending_target.sub(weights, fill_value=0.0).abs().sum())
            trade_cost = turnover * one_way_bps / 10_000
            cost += trade_cost
            trades.append(
                {
                    "date": date,
                    "signal_date": pending_signal,
                    "turnover": turnover,
                    "cost": trade_cost,
                    "holdings": len(pending_target),
                    "reason": "next_open_rebalance",
                }
            )
            for symbol, weight in pending_target.items():
                holdings.append(
                    {
                        "signal_date": pending_signal,
                        "execution_date": date,
                        "symbol": symbol,
                        "factor": pending_meta["factors"].get(symbol, np.nan),
                        "weight": weight,
                    }
                )
            weights = pending_target
            pending_target = None
            pending_signal = None
            pending_meta = {}

        if not weights.empty:
            intraday = (close_prices / open_prices - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            gross_return += float((weights.reindex(intraday.index, fill_value=0.0) * intraday).sum())

        if date in signal_dates:
            eligible = dollar_volume.loc[date].ge(min_dollar_volume)
            if membership_on is not None:
                members = membership_on(date)
                eligible = eligible & pd.Series(
                    [column in members for column in closes.columns], index=closes.columns
                )
            raw_factor = factors.loc[date].where(eligible)
            if mode == "ew":
                selected = raw_factor.dropna().index.tolist()
            elif mode == "exclude_high":
                selected = select_exclude_high_max(raw_factor, exclude_frac)
            elif mode == "low_max":
                selected = select_low_max(raw_factor, portfolio_decile, max_portfolio_size)
            else:
                raise ValueError(f"unknown mode: {mode}")
            pending_target = equal_weights(selected, 1.0)
            pending_signal = date
            pending_meta = {"factors": raw_factor}

        net_return = gross_return - cost
        rows.append(
            {
                "date": date,
                "gross_return": gross_return,
                "cost": cost,
                "net_return": net_return,
                "equity": 0.0,
                "exposure": float(weights.sum()) if not weights.empty else 0.0,
            }
        )
        previous_close = close_prices

    results = pd.DataFrame(rows).set_index("date")
    results["equity"] = (1 + results["net_return"]).cumprod()
    return results, pd.DataFrame(holdings), pd.DataFrame(trades), pd.DataFrame(exit_events)
