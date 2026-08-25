"""Monthly cross-sectional backtest — H1/H3/H5/H6."""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pandas as pd

from ..data.membership import force_liquidate_index_exits
from ..data.universe import month_end_index, next_trading_day
from ..status import INDEX_EXIT
from .costs import SCENARIOS, CostScenario, trade_cost_fraction

TargetFn = Callable[[pd.Timestamp, set[str]], "object"]


def run_cross_sectional_backtest(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    *,
    target_fn: Callable[[pd.Timestamp, set[str]], tuple[pd.Series, list[dict], str]],
    membership_on: Optional[Callable[[pd.Timestamp], frozenset[str]]] = None,
    cost_scenario: str = "baseline",
    min_price: float = 5.0,
    min_adv_usd: float = 5_000_000,
) -> dict:
    """Signal at month-end close; execute next session open; costs before holding PnL day."""
    scenario: CostScenario = SCENARIOS[cost_scenario]
    common = opens.index.intersection(closes.index).intersection(volumes.index).sort_values()
    opens, closes, volumes = (df.reindex(common) for df in (opens, closes, volumes))
    month_ends = month_end_index(common)
    execute_map: dict[pd.Timestamp, pd.Timestamp] = {}
    for signal_date in month_ends:
        exec_date = next_trading_day(common, signal_date)
        if exec_date is not None:
            execute_map[exec_date] = pd.Timestamp(signal_date)

    weights = pd.Series(dtype=float)
    pending_target: Optional[pd.Series] = None
    pending_signal: Optional[pd.Timestamp] = None
    pending_audit: list[dict] = []
    previous_close = None
    equity_rows, targets, trades, exit_events, gate_rows = [], [], [], [], []

    for date in common:
        open_prices = opens.loc[date]
        close_prices = closes.loc[date]
        gross_return = 0.0
        cost = 0.0

        # Overnight holding return from prior close to today open
        if previous_close is not None and not weights.empty:
            overnight = (open_prices / previous_close - 1).replace([np.inf, -np.inf], np.nan)
            # Missing prices: do NOT fill 0 silently — drop weight contribution and audit
            missing = overnight[weights.reindex(overnight.index, fill_value=0) > 0].isna()
            if missing.any():
                for symbol in missing[missing].index:
                    gate_rows.append({"date": date, "symbol": symbol, "event": "MISSING_PRICE_SKIP"})
                overnight = overnight.fillna(0.0)
            else:
                overnight = overnight.fillna(0.0)
            gross_return += float((weights.reindex(overnight.index, fill_value=0.0) * overnight).sum())

        # H1: INDEX_EXIT liquidation (not DELISTING)
        if membership_on is not None and not weights.empty:
            members = membership_on(date)
            weights, events = force_liquidate_index_exits(weights, members, date)
            for event in events:
                assert event["event"] == INDEX_EXIT
                exit_events.append(event)
            if events:
                liquidated = sum(abs(e["weight_before_exit"]) for e in events)
                c = trade_cost_fraction(liquidated, scenario=scenario)
                cost += c
                trades.append(
                    {
                        "date": date,
                        "turnover": liquidated,
                        "cost": c,
                        "reason": INDEX_EXIT,
                    }
                )

        # Execute pending rebalance at open (H5 steps 7–8: cost then intraday)
        if date in execute_map and pending_target is not None:
            turnover = float(pending_target.sub(weights, fill_value=0.0).abs().sum())
            # ADV participation approx
            adv = (closes * volumes).loc[:date].tail(20).mean()
            participations = []
            delta = pending_target.sub(weights, fill_value=0.0).abs()
            for symbol, d_w in delta.items():
                if d_w <= 0 or symbol not in adv.index or not np.isfinite(adv[symbol]) or adv[symbol] <= 0:
                    continue
                notional = d_w * 1_000_000
                participations.append(notional / float(adv[symbol]))
            avg_part = float(np.mean(participations)) if participations else 0.0
            trade_cost = trade_cost_fraction(turnover, scenario=scenario, avg_adv_participation=avg_part)
            cost += trade_cost
            trades.append(
                {
                    "date": date,
                    "signal_date": pending_signal,
                    "turnover": turnover,
                    "cost": trade_cost,
                    "avg_adv_participation": avg_part,
                    "reason": "next_open_rebalance",
                }
            )
            for symbol, weight in pending_target.items():
                targets.append(
                    {
                        "signal_date": pending_signal,
                        "execution_date": date,
                        "symbol": symbol,
                        "weight": float(weight),
                    }
                )
            for row in pending_audit:
                gate_rows.append({"date": date, **row})
            weights = pending_target
            pending_target = None
            pending_signal = None
            pending_audit = []

        if not weights.empty:
            intraday = (close_prices / open_prices - 1).replace([np.inf, -np.inf], np.nan)
            if intraday[weights.reindex(intraday.index, fill_value=0) > 0].isna().any():
                gate_rows.append({"date": date, "event": "MISSING_INTRADAY"})
            intraday = intraday.fillna(0.0)
            gross_return += float((weights.reindex(intraday.index, fill_value=0.0) * intraday).sum())

        if date in set(month_ends):
            prev_names = set(weights.index)
            target, audit, status = target_fn(date, prev_names)
            if status == "BLOCKED":
                gate_rows.append({"date": date, "status": "BLOCKED", "audit": audit})
                pending_target = pd.Series(dtype=float)
            else:
                # Weight sum check
                if not target.empty and abs(target.sum() - 1.0) > 1e-6:
                    target = target / target.sum()
                pending_target = target
            pending_signal = date
            pending_audit = audit

        net_return = gross_return - cost
        equity_rows.append(
            {
                "date": date,
                "gross_return": gross_return,
                "cost": cost,
                "net_return": net_return,
                "n_holdings": int((weights > 0).sum()) if not weights.empty else 0,
                "exposure": float(weights.sum()) if not weights.empty else 0.0,
            }
        )
        previous_close = close_prices

    equity = pd.DataFrame(equity_rows).set_index("date").sort_index()
    if trades:
        first_exec = pd.Timestamp(min(t["date"] for t in trades if "date" in t))
        equity = equity.loc[equity.index >= first_exec]
    if not equity.empty:
        equity["equity_gross"] = (1 + equity["gross_return"]).cumprod()
        equity["equity_net"] = (1 + equity["net_return"]).cumprod()
    return {
        "equity": equity,
        "targets": pd.DataFrame(targets),
        "trades": pd.DataFrame(trades),
        "exits": pd.DataFrame(exit_events),
        "gates": pd.DataFrame(gate_rows),
        "cost_scenario": cost_scenario,
        "return_basis": "Yahoo_AdjClose_scaled_Open",
    }
