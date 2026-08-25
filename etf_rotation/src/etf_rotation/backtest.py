"""Float-share vector and lot-constrained event-driven ETF backtests."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from etf_rotation.config import RotationConfig
from etf_rotation.strategy import (
    PortfolioState,
    choose_holdings,
    rebalance_dates,
    volatility_exposure,
)


def metrics(returns: pd.Series) -> dict[str, float]:
    values = pd.to_numeric(returns, errors="coerce").dropna()
    if values.empty:
        return {key: np.nan for key in (
            "total_return", "annual_return", "annual_volatility", "sharpe", "sortino",
            "max_drawdown", "calmar", "win_rate", "profit_factor",
        )}
    nav = (1 + values).cumprod()
    annual = nav.iloc[-1] ** (252 / len(values)) - 1
    vol = values.std(ddof=1) * np.sqrt(252) if len(values) > 1 else np.nan
    downside = values.loc[values < 0].std(ddof=1) * np.sqrt(252)
    drawdown = nav / nav.cummax() - 1
    gains, losses = values.loc[values > 0].sum(), values.loc[values < 0].sum()
    return {"total_return": float(nav.iloc[-1] - 1), "annual_return": float(annual),
            "annual_volatility": float(vol), "sharpe": float(annual / vol) if vol else np.nan,
            "sortino": float(annual / downside) if downside else np.nan,
            "max_drawdown": float(drawdown.min()),
            "calmar": float(annual / abs(drawdown.min())) if drawdown.min() < 0 else np.nan,
            "win_rate": float((values > 0).mean()),
            "profit_factor": float(gains / abs(losses)) if losses < 0 else np.nan}


def _maps(prices: dict[str, pd.DataFrame]) -> tuple[pd.DatetimeIndex, dict[str, pd.DataFrame]]:
    frames = {}
    for code, frame in prices.items():
        prepared = frame.sort_values("date").set_index("date").copy()
        prepared["close_return"] = prepared["close"].pct_change()
        frames[code] = prepared
    dates = pd.DatetimeIndex(sorted(set().union(*(set(frame.index) for frame in frames.values()))))
    return dates, frames


def build_targets(scores: pd.DataFrame, prices: dict[str, pd.DataFrame], config: RotationConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create decision-date holdings and target exposure with signal available on close."""
    dates, _ = _maps(prices)
    proxy = prices.get(config.regime_proxy)
    if proxy is None:
        raise ValueError(f"regime proxy {config.regime_proxy} unavailable")
    exposures = volatility_exposure(proxy, config) if config.use_regime_gate else pd.Series(1.0, index=dates)
    state, rows, trades = PortfolioState(), [], []
    score_dates = pd.DatetimeIndex(sorted(pd.to_datetime(scores["date"]).unique()))
    for date in rebalance_dates(score_dates, config.frequency):
        day = scores.loc[pd.to_datetime(scores["date"]).eq(date)].copy()
        selected, actions = choose_holdings(day, state, config)
        for code in state.holdings:
            state.holding_days[code] = state.holding_days.get(code, 0) + config.frequency
        for code in selected:
            state.holding_days.setdefault(code, 0)
        for action in actions:
            if action["action"] == "sell":
                state.holding_days.pop(action["code"], None)
        state.holdings = selected
        future = dates[dates > date]
        execution_date = future[0] if len(future) else pd.NaT
        exposure = float(exposures.reindex([date], method="ffill").iloc[0])
        if not np.isfinite(exposure):
            exposure = 1.0
        rows.append({"signal_date": date, "execution_date": execution_date, "holdings": "|".join(selected),
                     "exposure": exposure, "regime_exposure": exposure,
                     "rebalance_reason": "|".join(action["action"] for action in actions) or "hold"})
        trades.extend({"signal_date": date, "execution_date": execution_date, **action} for action in actions)
    return pd.DataFrame(rows), pd.DataFrame(trades)


def _current_target(targets: pd.DataFrame, date: pd.Timestamp) -> pd.Series | None:
    active = targets.loc[targets["execution_date"] <= date]
    return active.iloc[-1] if not active.empty else None


def vector_backtest(scores: pd.DataFrame, prices: dict[str, pd.DataFrame], config: RotationConfig) -> dict[str, object]:
    dates, frames = _maps(prices)
    targets, trades = build_targets(scores, prices, config)
    values, prior_weights = [], {}
    for date in dates:
        target = _current_target(targets, date)
        if target is None:
            values.append({"date": date, "return": 0.0, "exposure": 0.0, "turnover": 0.0})
            continue
        codes = [code for code in target.holdings.split("|") if code]
        weights = {code: float(target.exposure) / len(codes) for code in codes}
        daily_return = 0.0
        for code, weight in weights.items():
            frame = frames.get(code)
            if frame is not None and date in frame.index:
                ret = frame["close_return"].get(date, np.nan)
                if pd.notna(ret):
                    daily_return += weight * float(ret)
        turnover = sum(abs(weights.get(code, 0) - prior_weights.get(code, 0)) for code in set(weights) | set(prior_weights))
        daily_return -= turnover * config.commission_a_share
        values.append({"date": date, "return": daily_return, "exposure": target.exposure, "turnover": turnover})
        prior_weights = weights
    equity = pd.DataFrame(values)
    equity["nav"] = (1 + equity["return"]).cumprod()
    daily_targets = equity[["date", "exposure"]].merge(
        targets[["execution_date", "holdings", "rebalance_reason"]], how="left",
        left_on="date", right_on="execution_date",
    )
    daily_targets["holdings"] = daily_targets["holdings"].ffill().fillna("")
    daily_targets["rebalance_reason"] = daily_targets["rebalance_reason"].fillna("hold")
    return {"engine": "VEC", "targets": targets, "daily_targets": daily_targets,
            "trades": trades, "equity": equity,
            "metrics": metrics(equity["return"]), "config": config}


def event_backtest(scores: pd.DataFrame, prices: dict[str, pd.DataFrame], config: RotationConfig) -> dict[str, object]:
    """Integer 100-share cash simulation; trades occur using the same VEC targets."""
    dates, frames = _maps(prices)
    targets, signal_trades = build_targets(scores, prices, config)
    cash, shares, values, executions = config.initial_capital, {}, [], []
    last_target = None
    for date in dates:
        target = _current_target(targets, date)
        if target is not None and (last_target is None or target.execution_date != last_target.execution_date):
            codes = [code for code in target.holdings.split("|") if code]
            desired = set(codes)
            for code, qty in list(shares.items()):
                if code not in desired and date in frames[code].index:
                    price = float(frames[code].loc[date, "open"])
                    if not np.isfinite(price) or price <= 0:
                        executions.append({"date": date, "action": "sell", "code": code, "shares": qty,
                                           "price": price, "fee": 0.0, "status": "unfilled",
                                           "reason": "invalid_open_price"})
                        continue
                    fee = qty * price * config.commission_a_share
                    cash += qty * price - fee
                    executions.append({"date": date, "action": "sell", "code": code, "shares": qty,
                                       "price": price, "fee": fee, "status": "filled", "reason": ""})
                    del shares[code]
            allocation = cash * float(target.exposure) / max(len(codes), 1)
            if not np.isfinite(allocation) or allocation < 0:
                raise RuntimeError(f"{date}: invalid event-engine cash/allocation state")
            for code in codes:
                if code not in shares and date in frames[code].index:
                    price = float(frames[code].loc[date, "open"])
                    if not np.isfinite(price) or price <= 0:
                        executions.append({"date": date, "action": "buy", "code": code, "shares": 0,
                                           "price": price, "fee": 0.0, "status": "unfilled",
                                           "reason": "invalid_open_price"})
                        continue
                    qty = int(allocation / (price * 100 * (1 + config.commission_a_share))) * 100
                    adv = frames[code].loc[:date, "amount"].iloc[:-1].tail(20).mean()
                    cap = float(adv) * config.max_order_adv_pct if pd.notna(adv) else np.nan
                    if pd.notna(cap) and qty * price > cap:
                        qty = int(cap / (price * 100)) * 100
                    if qty:
                        fill_price = price * (1 + config.slippage_rate)
                        fee = qty * fill_price * config.commission_a_share
                        cost = qty * fill_price + fee
                        if cost <= cash:
                            cash -= cost
                            shares[code] = qty
                            executions.append({"date": date, "action": "buy", "code": code, "shares": qty,
                                               "price": fill_price, "fee": fee, "status": "filled",
                                               "reason": "adv_capped" if pd.notna(cap) and qty * price >= cap else ""})
                        else:
                            executions.append({"date": date, "action": "buy", "code": code, "shares": qty,
                                               "price": fill_price, "fee": 0.0, "status": "unfilled",
                                               "reason": "insufficient_cash"})
                    else:
                        executions.append({"date": date, "action": "buy", "code": code, "shares": 0,
                                           "price": price, "fee": 0.0, "status": "unfilled",
                                           "reason": "lot_or_adv_constraint"})
            last_target = target
        value = cash + sum(qty * float(frames[code].loc[date, "close"])
                           for code, qty in shares.items() if date in frames[code].index)
        values.append({"date": date, "value": value, "cash": cash, "holdings": "|".join(sorted(shares))})
    equity = pd.DataFrame(values)
    equity["return"] = equity["value"].pct_change().fillna(0.0)
    equity["nav"] = equity["value"] / config.initial_capital
    daily_positions = equity[["date", "cash", "holdings", "value"]].copy()
    return {"engine": "EVT", "targets": targets, "daily_positions": daily_positions,
            "trades": pd.DataFrame(executions),
            "signal_trades": signal_trades, "equity": equity, "metrics": metrics(equity["return"]), "config": config}


def variant_config(base: RotationConfig, variant: str) -> RotationConfig:
    options = {
        "M1": {"use_hysteresis": False, "use_regime_gate": False, "factor_set": "momentum"},
        "M2": {"use_hysteresis": False, "use_regime_gate": False, "factor_set": "momentum"},
        "H1": {"use_hysteresis": True, "use_regime_gate": False, "factor_set": "momentum"},
        "R1": {"use_hysteresis": True, "use_regime_gate": True, "factor_set": "momentum"},
        "C4": {"use_hysteresis": True, "use_regime_gate": True, "factor_set": "core_4f"},
        "C1": {"use_hysteresis": True, "use_regime_gate": True, "factor_set": "composite_1"},
        "v8_reference": {"use_hysteresis": True, "use_regime_gate": True, "factor_set": "composite_1"},
    }
    if variant not in options:
        raise ValueError(f"unknown variant {variant}")
    return replace(base, variant=variant, **options[variant])
