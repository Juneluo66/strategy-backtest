"""Monthly MAX portfolio simulator: signal at prior close, fill at next open."""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pandas as pd

from .factors import max_factor, monthly_signal_dates, vix_leverage
from .neutralization import controlled_factor, rolling_beta, rolling_volatility
from .portfolio import equal_weights, select_high_max, select_low_max
from .status import DELISTING_RETURN_UNAVAILABLE, INDEX_EXIT

MembershipFn = Callable[[pd.Timestamp], frozenset[str]]


def run_backtest(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    vix: pd.Series,
    *,
    lookback: int = 21,
    top_returns: int = 5,
    min_dollar_volume: float = 5_000_000,
    portfolio_decile: float = 0.10,
    max_portfolio_size: int = 25,
    vix_mode: str = "none",
    one_way_bps: float = 5.0,
    annual_margin_rate: float = 0.05,
    benchmark: Optional[pd.Series] = None,
    factor_variant: str = "raw",
    volatility_lookback_days: int = 63,
    beta_lookback_days: int = 252,
    beta_min_observations: int = 126,
    winsor_limits: tuple[float, float] = (0.025, 0.975),
    annual_spy_borrow_rate: float = 0.003,
    membership_on: Optional[MembershipFn] = None,
    selection: str = "low",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Signal on completed close; execute next session open; audit index exits."""
    common = opens.index.intersection(closes.index).intersection(volumes.index)
    opens, closes, volumes = (frame.reindex(common).sort_index() for frame in (opens, closes, volumes))
    returns = closes.pct_change(fill_method=None)
    factors = returns.apply(max_factor, lookback=lookback, top_returns=top_returns)
    benchmark_close = benchmark.reindex(common).ffill() if benchmark is not None else None
    benchmark_returns = (
        benchmark_close.pct_change(fill_method=None) if benchmark_close is not None else pd.Series(0.0, index=common)
    )
    volatility = rolling_volatility(returns, volatility_lookback_days)
    beta = rolling_beta(returns, benchmark_returns, beta_lookback_days, beta_min_observations)
    dollar_volume = (closes * volumes).rolling(lookback, min_periods=lookback).mean()
    signal_dates = set(monthly_signal_dates(common))
    execute_map: dict[pd.Timestamp, pd.Timestamp] = {}
    ordered = list(common)
    for signal_date in monthly_signal_dates(common):
        position = ordered.index(signal_date)
        if position + 1 < len(ordered):
            execute_map[ordered[position + 1]] = signal_date

    weights = pd.Series(dtype=float)
    pending_target: Optional[pd.Series] = None
    pending_signal: Optional[pd.Timestamp] = None
    pending_meta: dict = {}
    hedge_weight = 0.0
    rows: list[dict] = []
    holdings: list[dict] = []
    trades: list[dict] = []
    exit_events: list[dict] = []
    previous_close = None
    previous_bench = None

    for date in common:
        open_prices = opens.loc[date]
        close_prices = closes.loc[date]
        gross_return = 0.0
        cost = 0.0

        if previous_close is not None and not weights.empty:
            overnight = (open_prices / previous_close - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            gross_return += float((weights.reindex(overnight.index, fill_value=0.0) * overnight).sum())
            if hedge_weight and previous_bench is not None and benchmark_close is not None:
                # Approximate hedge with close-to-close when benchmark opens are unavailable.
                gross_return += hedge_weight * float(benchmark_returns.get(date, 0.0) or 0.0)

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
                        "leverage": float(weights.drop(labels=exited).sum()),
                        "hedge_weight": hedge_weight,
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
                    "leverage": float(pending_target.sum()) if not pending_target.empty else 0.0,
                    "hedge_weight": pending_meta.get("hedge_weight", 0.0),
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
                        "beta": pending_meta["betas"].get(symbol, np.nan),
                    }
                )
            weights = pending_target
            hedge_weight = float(pending_meta.get("hedge_weight", 0.0))
            pending_target = None
            pending_signal = None
            pending_meta = {}

        if not weights.empty:
            intraday = (close_prices / open_prices - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            gross_return += float((weights.reindex(intraday.index, fill_value=0.0) * intraday).sum())

        if date in signal_dates:
            known_vix = vix.reindex(common).ffill().shift(1).loc[date]
            eligible = dollar_volume.loc[date].ge(min_dollar_volume)
            if membership_on is not None:
                members = membership_on(date)
                eligible = eligible & pd.Series([column in members for column in closes.columns], index=closes.columns)
            raw_factor = factors.loc[date].where(eligible)
            if factor_variant == "size_neutral":
                raise RuntimeError("BLOCKED_BY_PIT_MARKET_CAP")
            candidates = (
                raw_factor
                if factor_variant in {"raw", "beta_hedged"}
                else controlled_factor(
                    raw_factor, volatility.loc[date], beta.loc[date], factor_variant, winsor_limits
                )
            )
            selected = (
                select_high_max(candidates, portfolio_decile, max_portfolio_size)
                if selection == "high"
                else select_low_max(candidates, portfolio_decile, max_portfolio_size)
            )
            leverage = vix_leverage(known_vix, vix_mode)
            pending_target = equal_weights(selected, leverage)
            pending_signal = date
            selected_beta = float(beta.loc[date, selected].mean()) if selected else 0.0
            pending_meta = {
                "factors": candidates,
                "betas": beta.loc[date],
                "hedge_weight": (-selected_beta * leverage) if factor_variant == "beta_hedged" else 0.0,
            }

        leverage_cost = max(float(weights.sum()) - 1.0, 0.0) * annual_margin_rate / 252
        borrow_cost = max(-hedge_weight, 0.0) * annual_spy_borrow_rate / 252
        net_return = gross_return - cost - leverage_cost - borrow_cost
        rows.append(
            {
                "date": date,
                "gross_return": gross_return,
                "cost": cost + leverage_cost + borrow_cost,
                "net_return": net_return,
                "equity": 0.0,
                "exposure": float(weights.sum()) + hedge_weight,
                "hedge_weight": hedge_weight,
            }
        )
        previous_close = close_prices
        previous_bench = benchmark_close.loc[date] if benchmark_close is not None else None

    results = pd.DataFrame(rows).set_index("date")
    results["equity"] = (1 + results["net_return"]).cumprod()
    return results, pd.DataFrame(holdings), pd.DataFrame(trades), pd.DataFrame(exit_events)
