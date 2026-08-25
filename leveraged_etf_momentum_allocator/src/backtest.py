"""Backtest engine for conditional_leveraged_etf_rotation."""
from __future__ import annotations

from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from config import ProjectConfig
from data_loader import inception_date
from execution import ExecutionMode
from indicators import build_indicator_panels, indicators_ready
from original_strategy import DecisionResult, load_thresholds, select_target, state_from_row


def effective_common_start(closes: pd.DataFrame, universe: list[str], warmup: int) -> pd.Timestamp:
    """Latest inception across universe + warmup trading days."""
    inceptions = []
    for t in universe:
        inc = inception_date(closes, t)
        if inc is not None:
            inceptions.append(inc)
    if not inceptions:
        raise ValueError("no inception dates found")
    latest_inc = max(inceptions)
    cal = closes.index[closes.index >= latest_inc]
    if len(cal) <= warmup:
        raise ValueError("insufficient history after inception for warmup")
    return pd.Timestamp(cal[warmup])


def run_conditional_rotation(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    cfg: ProjectConfig,
    *,
    mode: ExecutionMode = ExecutionMode.QC_DAILY_SEMANTICS,
    start: Optional[str] = None,
    end: Optional[str] = None,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
    thresholds: Optional[dict] = None,
    parameters_override: Optional[dict] = None,
    target_selector: Optional[Callable] = None,
    execution_map: Optional[dict[str, str]] = None,
    indicator_cache: Optional[dict] = None,
    label: str = "ORIGINAL",
) -> dict[str, Any]:
    """Run decision-tree or baseline strategy with explicit execution mode."""
    params = dict(cfg.parameters())
    if parameters_override:
        params.update(parameters_override)
    universe = cfg.universe()
    warmup = cfg.warmup_bars()
    thresh = thresholds or load_thresholds(cfg)
    cost_bps = commission_bps + slippage_bps
    selector = target_selector or select_target

    cal = closes.index.intersection(opens.index).sort_values()
    opens = opens.reindex(cal)
    closes = closes.reindex(cal)

    ind_key = (
        int(params["rsi_period"]),
        int(params["spy_sma_period"]),
        int(params["qqq_sma_period"]),
        int(params["tqqq_sma_period"]),
    )
    if indicator_cache is not None and ind_key in indicator_cache:
        indicators = indicator_cache[ind_key]
    else:
        indicators = build_indicator_panels(
            closes,
            rsi_period=int(params["rsi_period"]),
            spy_sma_period=int(params["spy_sma_period"]),
            qqq_sma_period=int(params["qqq_sma_period"]),
            tqqq_sma_period=int(params["tqqq_sma_period"]),
            universe=universe,
        )
        if indicator_cache is not None:
            indicator_cache[ind_key] = indicators
    rsi = indicators["rsi"]
    sma = indicators["sma"]

    eff_start = effective_common_start(closes, universe, warmup)
    req_start = pd.Timestamp(start or cfg.requested_start())
    trade_start = max(eff_start, req_start)

    if end:
        cal = cal[cal <= pd.Timestamp(end)]
    cal = cal[cal >= trade_start]
    if cal.empty:
        raise ValueError("empty calendar after date filters")

    cash = cfg.initial_cash()
    holding: Optional[str] = None
    shares = 0.0
    pending_target: Optional[str] = None
    pending_decision: Optional[DecisionResult] = None
    day_cost: float = 0.0

    equity_rows: list[dict] = []
    signal_log: list[dict] = []
    trades: list[dict] = []
    decision_count = 0
    target_change_count = 0
    actual_trade_count = 0
    first_signal_date: Optional[pd.Timestamp] = None
    first_trade_date: Optional[pd.Timestamp] = None
    previous_target: Optional[str] = None

    def _execute(date: pd.Timestamp, px: pd.Series, signal_date: pd.Timestamp, target: str) -> None:
        nonlocal cash, holding, shares, actual_trade_count, first_trade_date, day_cost
        if target == holding and holding is not None:
            return
        nav = cash + (shares * float(px.get(holding, 0)) if holding else 0)
        if holding and shares > 0:
            sell_px = float(px.get(holding, np.nan))
            if np.isfinite(sell_px) and sell_px > 0:
                proceeds = shares * sell_px
                fee = proceeds * cost_bps / 10_000
                cash += proceeds - fee
                day_cost += fee
                trades.append(_leg(date, signal_date, holding, "sell", shares, sell_px, fee))
                actual_trade_count += 1
                shares = 0.0
        buy_px = float(px.get(target, np.nan))
        if target == "CASH" or (not np.isfinite(buy_px) or buy_px <= 0):
            holding = None
            shares = 0.0
            return
        nav = cash
        shares = nav / buy_px
        fee = nav * cost_bps / 10_000
        cash = -fee
        day_cost += fee
        shares = (nav - fee) / buy_px
        trades.append(_leg(date, signal_date, target, "buy", shares, buy_px, fee))
        actual_trade_count += 1
        holding = target
        if first_trade_date is None:
            first_trade_date = date

    for i, date in enumerate(cal):
        close_px = closes.loc[date]
        open_px = opens.loc[date]

        ready = indicators_ready(
            date,
            closes,
            indicators,
            universe,
            rsi_period=int(params["rsi_period"]),
            spy_sma_period=int(params["spy_sma_period"]),
            warmup_bars=warmup,
        )

        gross_ret = 0.0
        cost_drag = 0.0
        day_cost = 0.0
        nav_start = cash + (shares * float(close_px.get(holding, 0)) if holding else 0.0)

        if mode == ExecutionMode.QC_DAILY_SEMANTICS:
            # Full day return on current holding (close-to-close from prev)
            if i > 0 and holding:
                prev = cal[i - 1]
                p0 = float(closes.loc[prev, holding])
                p1 = float(close_px[holding])
                if np.isfinite(p0) and p0 > 0 and np.isfinite(p1):
                    gross_ret = p1 / p0 - 1

            if ready:
                st = state_from_row(date, closes, rsi, sma)
                decision = selector(st, thresh)
                decision_count += 1
                if first_signal_date is None:
                    first_signal_date = date
                target_changed = decision.target != previous_target
                if target_changed:
                    target_change_count += 1
                signal_log.append(_log_row(date, st, decision, previous_target, target_changed))
                trade_target = execution_map.get(decision.target, decision.target) if execution_map else decision.target
                if trade_target != holding:
                    _execute(date, close_px, date, trade_target)
                previous_target = decision.target

        elif mode == ExecutionMode.NEXT_OPEN_CONSERVATIVE:
            # Execute pending from yesterday at today's open
            if pending_target is not None:
                _execute(date, open_px, pending_decision and cal[i - 1] or date, pending_target)
                pending_target = None
                pending_decision = None
            # Intraday + overnight return on holding
            if i > 0 and holding:
                prev = cal[i - 1]
                p_prev_close = float(closes.loc[prev, holding])
                p_open = float(open_px[holding])
                p_close = float(close_px[holding])
                if np.isfinite(p_prev_close) and p_prev_close > 0:
                    if np.isfinite(p_open):
                        gross_ret += p_open / p_prev_close - 1
                    if np.isfinite(p_open) and p_open > 0 and np.isfinite(p_close):
                        gross_ret += p_close / p_open - 1

            if ready:
                st = state_from_row(date, closes, rsi, sma)
                decision = selector(st, thresh)
                decision_count += 1
                if first_signal_date is None:
                    first_signal_date = date
                target_changed = decision.target != previous_target
                if target_changed:
                    target_change_count += 1
                signal_log.append(_log_row(date, st, decision, previous_target, target_changed))
                trade_target = execution_map.get(decision.target, decision.target) if execution_map else decision.target
                if trade_target != holding:
                    pending_target = trade_target
                    pending_decision = decision
                previous_target = decision.target

        else:  # NEXT_CLOSE_RESEARCH
            if i > 0 and holding:
                prev = cal[i - 1]
                p0 = float(closes.loc[prev, holding])
                p1 = float(close_px[holding])
                if np.isfinite(p0) and p0 > 0:
                    gross_ret = p1 / p0 - 1
            if pending_target is not None:
                _execute(date, close_px, cal[i - 1], pending_target)
                pending_target = None
            if ready:
                st = state_from_row(date, closes, rsi, sma)
                decision = selector(st, thresh)
                decision_count += 1
                if first_signal_date is None:
                    first_signal_date = date
                target_changed = decision.target != previous_target
                if target_changed:
                    target_change_count += 1
                signal_log.append(_log_row(date, st, decision, previous_target, target_changed))
                if decision.target != holding:
                    pending_target = decision.target
                previous_target = decision.target

        nav_end = cash + (shares * float(close_px.get(holding, 0)) if holding else cash)
        if nav_start > 0:
            cost_drag = day_cost / nav_start
            net_ret = gross_ret - cost_drag
        else:
            net_ret = 0.0
        equity_rows.append(
            {
                "date": date,
                "holding": holding,
                "gross_return": gross_ret,
                "cost": cost_drag,
                "net_return": net_ret,
                "nav": nav_end,
            }
        )

    equity = pd.DataFrame(equity_rows).set_index("date")
    equity["equity_gross"] = (1 + equity["gross_return"]).cumprod()
    equity["equity_net"] = (1 + equity["net_return"]).cumprod()

    inceptions = {t: inception_date(closes, t) for t in universe}

    return {
        "equity": equity,
        "trades": pd.DataFrame(trades),
        "signal_log": pd.DataFrame(signal_log),
        "mode": mode.value,
        "requested_start": str(req_start.date()),
        "effective_start": str(trade_start.date()),
        "end": str(cal[-1].date()),
        "first_signal_date": str(first_signal_date.date()) if first_signal_date else None,
        "first_trade_date": str(first_trade_date.date()) if first_trade_date else None,
        "decision_count": decision_count,
        "target_change_count": target_change_count,
        "actual_trade_count": actual_trade_count,
        "inceptions": {k: str(v.date()) if v else None for k, v in inceptions.items()},
        "commission_bps": commission_bps,
        "slippage_bps": slippage_bps,
        "label": label,
    }


def _leg(date, signal_date, ticker, side, shares, px, fee) -> dict:
    return {
        "date": date,
        "signal_date": signal_date,
        "execution_date": date,
        "ticker": ticker,
        "side": side,
        "shares": shares,
        "execution_price": px,
        "commission": fee,
        "slippage": 0.0,
        "turnover": 1.0 if side == "buy" else 1.0,
    }


def _log_row(date, st, decision: DecisionResult, prev_target, target_changed: bool) -> dict:
    return {
        "date": date,
        "price_spy": st.price_spy,
        "spy_sma_200": st.spy_sma_200,
        "price_qqq": st.price_qqq,
        "qqq_sma_20": st.qqq_sma_20,
        "price_tqqq": st.price_tqqq,
        "tqqq_sma_20": st.tqqq_sma_20,
        "rsi_qqq": st.rsi_qqq,
        "rsi_spy": st.rsi_spy,
        "rsi_tqqq": st.rsi_tqqq,
        "rsi_sqqq": st.rsi_sqqq,
        "rsi_uvxy": st.rsi_uvxy,
        "rsi_tecs": st.rsi_tecs,
        "rsi_bsv": st.rsi_bsv,
        "market_regime": decision.regime,
        "branch_path": " → ".join(decision.branch_path),
        "branch_id": decision.branch_id,
        "branch_rule": decision.branch_rule,
        "target": decision.target,
        "previous_target": prev_target,
        "target_changed": target_changed,
    }
