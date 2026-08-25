"""Month-end signal → next-open execution with natural weight drift."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .calendar import month_end_index, next_trading_day, trading_day_plus_n


def _normalize(weights: pd.Series) -> pd.Series:
    total = float(weights.sum())
    if total <= 0:
        return weights * 0.0
    return weights / total


def run_weight_schedule(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    target_on_signal: dict[pd.Timestamp, pd.Series],
    *,
    one_way_bps: float = 5.0,
    execution_delay_sessions: int = 1,
    symbols: Optional[list[str]] = None,
) -> dict:
    """
    Execution model (fixed):
    - Signal formed on month-end close using data through that close.
    - Default: execute next trading session open (delay=1).
    - Stress: delay=2 means one extra session (signal+2 opens).
    - Between rebalances, holdings drift with asset total returns (share drift).
    - One-way cost = L1 turnover * one_way_bps / 1e4 on execution open.
    - Never fillna(0) on missing asset returns: days with any NaN in held
      names are dropped from the equity path (strict).
    """
    if execution_delay_sessions < 1:
        raise ValueError("execution_delay_sessions must be >= 1")

    cols = list(symbols) if symbols is not None else sorted(
        set().union(*[set(s.index) for s in target_on_signal.values()]) if target_on_signal else set()
    )
    if not cols:
        # Infer from panels
        cols = list(closes.columns)

    common = opens.index.intersection(closes.index).sort_values()
    opens = opens.reindex(common)[cols]
    closes = closes.reindex(common)[cols]

    execute_map: dict[pd.Timestamp, pd.Timestamp] = {}
    for signal in target_on_signal:
        exe = trading_day_plus_n(common, signal, execution_delay_sessions)
        if exe is not None:
            execute_map[pd.Timestamp(exe)] = pd.Timestamp(signal)

    weights = pd.Series(0.0, index=cols, dtype=float)
    pending: Optional[pd.Series] = None
    prev_close: Optional[pd.Series] = None
    rows: list[dict] = []
    trades: list[dict] = []
    targets_log: list[dict] = []
    weight_rows: list[dict] = []
    started = False

    for date in common:
        gross = 0.0
        cost = 0.0
        skip = False

        if prev_close is not None and started:
            overnight = opens.loc[date] / prev_close - 1.0
            held = weights[weights.abs() > 1e-15]
            if held.empty:
                pass
            elif overnight.reindex(held.index).isna().any():
                skip = True
            else:
                piece = overnight.reindex(held.index).astype(float)
                gross += float((weights.reindex(held.index) * piece).sum())
                grown = weights * (1.0 + overnight.fillna(0.0))
                # Only drift names we actually hold; keep exact zeros at zero
                grown = grown.where(weights.abs() > 1e-15, 0.0)
                weights = _normalize(grown.fillna(0.0))

        if (not skip) and date in execute_map and pending is not None:
            tgt = pending.reindex(cols).fillna(0.0)
            turnover = float((tgt - weights).abs().sum())
            cost = turnover * one_way_bps / 10_000.0
            trades.append(
                {
                    "date": date,
                    "signal_date": execute_map[date],
                    "turnover": turnover,
                    "cost": cost,
                    "one_way_bps": one_way_bps,
                }
            )
            for symbol, w in tgt.items():
                targets_log.append(
                    {
                        "signal_date": execute_map[date],
                        "execution_date": date,
                        "symbol": symbol,
                        "weight": float(w),
                    }
                )
            weights = tgt
            pending = None
            started = True

        if started and not skip and weights.abs().sum() > 1e-15:
            intraday = closes.loc[date] / opens.loc[date] - 1.0
            held = weights[weights.abs() > 1e-15]
            if intraday.reindex(held.index).isna().any() or opens.loc[date].reindex(held.index).isna().any():
                skip = True
            else:
                piece = intraday.reindex(held.index).astype(float)
                gross += float((weights.reindex(held.index) * piece).sum())
                grown = weights * (1.0 + intraday.fillna(0.0))
                grown = grown.where(weights.abs() > 1e-15, 0.0)
                weights = _normalize(grown.fillna(0.0))

        if date in target_on_signal:
            pending = target_on_signal[date].reindex(cols).fillna(0.0)

        if started and not skip:
            row = {
                "date": date,
                "gross_return": gross,
                "cost": cost,
                "net_return": gross - cost,
                "w_bil": float(weights.get("BIL", 0.0)) if "BIL" in weights.index else 0.0,
            }
            for sym in cols:
                row[f"w_{sym}"] = float(weights.get(sym, 0.0))
            rows.append(row)
            weight_rows.append({"date": date, **{sym: float(weights.get(sym, 0.0)) for sym in cols}})

        prev_close = closes.loc[date]

    equity = pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame(
        columns=["gross_return", "cost", "net_return"]
    )
    if not equity.empty:
        equity["equity_net"] = (1 + equity["net_return"]).cumprod()
        equity["equity_gross"] = (1 + equity["gross_return"]).cumprod()
    return {
        "equity": equity,
        "trades": pd.DataFrame(trades),
        "targets": pd.DataFrame(targets_log),
        "weights": pd.DataFrame(weight_rows).set_index("date") if weight_rows else pd.DataFrame(),
        "return_basis": "Yahoo_AdjClose_scaled_Open",
        "execution_delay_sessions": execution_delay_sessions,
        "one_way_bps": one_way_bps,
    }


def buy_and_hold(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    symbol: str,
) -> pd.DataFrame:
    """Single-asset buy-and-hold on total-return Adj Close path (no costs)."""
    common = opens.index.intersection(closes.index).sort_values()
    px = closes[symbol].reindex(common)
    # Use close-to-close total returns for BH (standard); no turnover.
    rets = px.pct_change(fill_method=None)
    # Drop first NaN; never fill with 0
    rets = rets.dropna()
    eq = pd.DataFrame(
        {
            "gross_return": rets,
            "cost": 0.0,
            "net_return": rets,
        },
        index=rets.index,
    )
    eq["equity_net"] = (1 + eq["net_return"]).cumprod()
    eq["equity_gross"] = eq["equity_net"]
    return eq


def monthly_rebalance_fixed(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    target_weights: dict[str, float],
    *,
    one_way_bps: float = 5.0,
    execution_delay_sessions: int = 1,
) -> dict:
    """Fixed mix with month-end signal / next-open execution and drift."""
    ends = month_end_index(closes.index)
    targets: dict[pd.Timestamp, pd.Series] = {}
    series = pd.Series(target_weights, dtype=float)
    series = series / series.sum()
    for date in ends:
        # Require all target names present that day
        if closes.loc[date, list(target_weights)].isna().any():
            continue
        targets[pd.Timestamp(date)] = series.copy()
    return run_weight_schedule(
        opens,
        closes,
        targets,
        one_way_bps=one_way_bps,
        execution_delay_sessions=execution_delay_sessions,
        symbols=list(target_weights.keys()),
    )
