"""IBKR-style paper trading constraints for sleeve portfolios (no live orders)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import yaml

from .config import DualMomentumConfig


@dataclass
class PaperConfig:
    initial_cash: float = 100_000.0
    allow_fractional_shares: bool = True
    min_commission: float = 1.0
    commission_per_share: float = 0.005
    min_order_notional: float = 1.0
    share_lot_size: float = 1.0  # when fractional disabled
    defer_residual_below_notional: float = 25.0  # leave small drift to next month
    one_way_bps: float = 5.0  # market impact / spread proxy in addition to commission
    forbid_negative_cash: bool = True


def load_paper_config(path: Path) -> PaperConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    keys = {f.name for f in PaperConfig.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    return PaperConfig(**{k: v for k, v in raw.items() if k in keys})


@dataclass
class PortfolioState:
    cash: float
    shares: dict[str, float] = field(default_factory=dict)
    deferred_targets: dict[str, float] = field(default_factory=dict)


def _commission(shares_traded: float, cfg: PaperConfig) -> float:
    raw = abs(shares_traded) * cfg.commission_per_share
    return max(raw, cfg.min_commission) if abs(shares_traded) > 1e-12 else 0.0


def _round_shares(qty: float, cfg: PaperConfig) -> float:
    if cfg.allow_fractional_shares:
        return float(qty)
    lot = cfg.share_lot_size
    return float(np.floor(qty / lot + 1e-12) * lot)


def mark_to_market(state: PortfolioState, prices: dict[str, float]) -> float:
    equity = state.cash
    for sym, qty in state.shares.items():
        px = prices.get(sym)
        if px is None or not np.isfinite(px):
            continue
        equity += qty * px
    return float(equity)


def execute_rebalance(
    state: PortfolioState,
    *,
    target_weights: dict[str, float],
    prices: dict[str, float],
    cfg: PaperConfig,
    asof: pd.Timestamp,
    portfolio_id: str,
) -> tuple[PortfolioState, list[dict[str, Any]], dict[str, float]]:
    """
    Convert target weights → orders under IBKR-like constraints.
    Prices must be executable (e.g. open). Missing prices → skip symbol, log rejection.
    """
    logs: list[dict[str, Any]] = []
    nav = mark_to_market(state, prices)
    if nav <= 0:
        logs.append(
            {
                "asof": str(asof.date()),
                "portfolio_id": portfolio_id,
                "event": "REJECT_ZERO_NAV",
                "nav": nav,
            }
        )
        return state, logs, {k: 0.0 for k in target_weights}

    # Merge deferred residual targets (soft)
    desired = dict(target_weights)
    for sym, w in state.deferred_targets.items():
        desired[sym] = desired.get(sym, 0.0)  # deferred is notional leftover intent logged only

    theoretical_shares = {}
    for sym, w in desired.items():
        px = prices.get(sym)
        if px is None or not np.isfinite(px) or px <= 0:
            logs.append(
                {
                    "asof": str(asof.date()),
                    "portfolio_id": portfolio_id,
                    "event": "PRICE_MISSING",
                    "symbol": sym,
                    "target_weight": w,
                }
            )
            theoretical_shares[sym] = state.shares.get(sym, 0.0)
            continue
        theoretical_shares[sym] = (nav * w) / px

    # Include symbols we hold but are no longer targeted
    for sym in list(state.shares.keys()):
        if sym not in theoretical_shares:
            theoretical_shares[sym] = 0.0

    new_shares = dict(state.shares)
    cash = float(state.cash)
    deferred: dict[str, float] = {}

    # Sell first to free cash
    sell_syms = [
        sym
        for sym, tgt in theoretical_shares.items()
        if tgt < new_shares.get(sym, 0.0) - 1e-12
    ]
    buy_syms = [
        sym
        for sym, tgt in theoretical_shares.items()
        if tgt > new_shares.get(sym, 0.0) + 1e-12
    ]

    def trade(sym: str, target_qty: float) -> None:
        nonlocal cash
        px = prices.get(sym)
        if px is None or not np.isfinite(px) or px <= 0:
            logs.append(
                {
                    "asof": str(asof.date()),
                    "portfolio_id": portfolio_id,
                    "event": "ORDER_REJECT_NO_PRICE",
                    "symbol": sym,
                }
            )
            return
        current = new_shares.get(sym, 0.0)
        delta = target_qty - current
        rounded = _round_shares(abs(delta), cfg) * (1 if delta > 0 else -1)
        if abs(rounded) < 1e-12:
            # residual too small after rounding
            notional = abs(delta) * px
            if notional < cfg.defer_residual_below_notional:
                deferred[sym] = desired.get(sym, 0.0)
                logs.append(
                    {
                        "asof": str(asof.date()),
                        "portfolio_id": portfolio_id,
                        "event": "DEFER_SMALL_RESIDUAL",
                        "symbol": sym,
                        "residual_notional": notional,
                        "theoretical_delta_shares": delta,
                    }
                )
            return

        order_notional = abs(rounded) * px
        if order_notional < cfg.min_order_notional:
            deferred[sym] = desired.get(sym, 0.0)
            logs.append(
                {
                    "asof": str(asof.date()),
                    "portfolio_id": portfolio_id,
                    "event": "ORDER_REJECT_MIN_NOTIONAL",
                    "symbol": sym,
                    "order_notional": order_notional,
                    "min_order_notional": cfg.min_order_notional,
                }
            )
            return

        commission = _commission(rounded, cfg)
        spread = order_notional * cfg.one_way_bps / 10_000
        total_cost = commission + spread

        if rounded < 0:
            # sell
            proceeds = abs(rounded) * px
            cash += proceeds - total_cost
            new_shares[sym] = current + rounded
            logs.append(
                {
                    "asof": str(asof.date()),
                    "portfolio_id": portfolio_id,
                    "event": "FILL",
                    "side": "SELL",
                    "symbol": sym,
                    "shares": rounded,
                    "price": px,
                    "notional": proceeds,
                    "commission": commission,
                    "spread_bps_cost": spread,
                    "theoretical_weight": desired.get(sym, 0.0),
                    "theoretical_shares": theoretical_shares.get(sym),
                }
            )
        else:
            # buy — may partial fill if cash insufficient
            need = rounded * px + total_cost
            if cfg.forbid_negative_cash and need > cash + 1e-9:
                # partial fill: spend almost all cash
                affordable = max(cash - cfg.min_commission, 0.0)
                if affordable < cfg.min_order_notional:
                    logs.append(
                        {
                            "asof": str(asof.date()),
                            "portfolio_id": portfolio_id,
                            "event": "ORDER_REJECT_INSUFFICIENT_CASH",
                            "symbol": sym,
                            "need": need,
                            "cash": cash,
                        }
                    )
                    return
                # solve qty * px + max(qty*cps, min_comm) + qty*px*bps ≈ affordable
                # approximate ignoring min commission interaction
                qty = affordable / (px * (1 + cfg.one_way_bps / 10_000) + cfg.commission_per_share)
                qty = _round_shares(qty, cfg)
                if qty <= 0:
                    logs.append(
                        {
                            "asof": str(asof.date()),
                            "portfolio_id": portfolio_id,
                            "event": "ORDER_REJECT_INSUFFICIENT_CASH",
                            "symbol": sym,
                            "cash": cash,
                        }
                    )
                    return
                rounded = qty
                order_notional = rounded * px
                commission = _commission(rounded, cfg)
                spread = order_notional * cfg.one_way_bps / 10_000
                total_cost = commission + spread
                cash -= order_notional + total_cost
                new_shares[sym] = current + rounded
                logs.append(
                    {
                        "asof": str(asof.date()),
                        "portfolio_id": portfolio_id,
                        "event": "PARTIAL_FILL",
                        "side": "BUY",
                        "symbol": sym,
                        "shares": rounded,
                        "price": px,
                        "notional": order_notional,
                        "commission": commission,
                        "spread_bps_cost": spread,
                        "theoretical_weight": desired.get(sym, 0.0),
                        "theoretical_shares": theoretical_shares.get(sym),
                    }
                )
            else:
                cash -= order_notional + total_cost
                if cfg.forbid_negative_cash and cash < -1e-6:
                    # rollback
                    cash += order_notional + total_cost
                    logs.append(
                        {
                            "asof": str(asof.date()),
                            "portfolio_id": portfolio_id,
                            "event": "ORDER_REJECT_NEGATIVE_CASH_GUARD",
                            "symbol": sym,
                        }
                    )
                    return
                new_shares[sym] = current + rounded
                logs.append(
                    {
                        "asof": str(asof.date()),
                        "portfolio_id": portfolio_id,
                        "event": "FILL",
                        "side": "BUY",
                        "symbol": sym,
                        "shares": rounded,
                        "price": px,
                        "notional": order_notional,
                        "commission": commission,
                        "spread_bps_cost": spread,
                        "theoretical_weight": desired.get(sym, 0.0),
                        "theoretical_shares": theoretical_shares.get(sym),
                    }
                )

    for sym in sell_syms:
        trade(sym, theoretical_shares[sym])
    for sym in buy_syms:
        trade(sym, theoretical_shares[sym])

    # Drop zero positions
    new_shares = {k: v for k, v in new_shares.items() if abs(v) > 1e-12}
    final_nav = mark_to_market(PortfolioState(cash=cash, shares=new_shares), prices)
    final_weights = {
        sym: (new_shares.get(sym, 0.0) * prices[sym] / final_nav)
        if final_nav > 0 and sym in prices and np.isfinite(prices[sym])
        else 0.0
        for sym in set(list(desired) + list(new_shares))
    }
    logs.append(
        {
            "asof": str(asof.date()),
            "portfolio_id": portfolio_id,
            "event": "REBALANCE_SUMMARY",
            "nav": final_nav,
            "cash": cash,
            "theoretical_weights": desired,
            "final_weights": final_weights,
            "shares": new_shares,
        }
    )
    return PortfolioState(cash=cash, shares=new_shares, deferred_targets=deferred), logs, final_weights


def simulate_spy_only_paper(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    cfg: PaperConfig,
    *,
    portfolio_id: str = "100_spy",
) -> dict[str, Any]:
    """Buy SPY once (or top-up monthly to 100%) under paper constraints."""
    idx = opens.index.intersection(closes.index).sort_values()
    state = PortfolioState(cash=cfg.initial_cash)
    all_logs: list[dict[str, Any]] = []
    equity_rows = []
    # initial buy on first open
    first = idx[0]
    state, logs, _ = execute_rebalance(
        state,
        target_weights={"SPY": 1.0},
        prices={"SPY": float(opens.loc[first, "SPY"])},
        cfg=cfg,
        asof=first,
        portfolio_id=portfolio_id,
    )
    all_logs.extend(logs)
    prev_nav = None
    for date in idx:
        px_close = {"SPY": float(closes.loc[date, "SPY"])}
        nav = mark_to_market(state, px_close)
        ret = 0.0 if prev_nav is None else nav / prev_nav - 1
        equity_rows.append({"date": date, "net_return": ret, "nav": nav, "cash": state.cash})
        prev_nav = nav
    eq = pd.DataFrame(equity_rows).set_index("date")
    eq["equity_net"] = eq["nav"] / eq["nav"].iloc[0]
    return {"equity": eq, "logs": all_logs, "final_state": asdict(state), "portfolio_id": portfolio_id}


def simulate_two_asset_paper(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    *,
    targets: dict[str, float],
    rebalance_execution_dates: list[pd.Timestamp],
    cfg: PaperConfig,
    portfolio_id: str,
    cash_symbol_resolver=None,
) -> dict[str, Any]:
    """
    Monthly (precomputed) execution dates: rebalance at OPEN prices toward targets.
    For CASH sleeve, resolver(date) -> SGOV or BIL.
    """
    idx = opens.index.intersection(closes.index).sort_values()
    exec_set = set(pd.Timestamp(d) for d in rebalance_execution_dates)
    state = PortfolioState(cash=cfg.initial_cash)
    all_logs: list[dict[str, Any]] = []
    equity_rows = []
    prev_nav = None

    # Bootstrap on first exec or first day
    bootstrap = True
    for date in idx:
        # Mark overnight move on opens for held assets before rebalance
        open_prices = {}
        for sym in list(state.shares.keys()) + list(targets.keys()):
            if sym == "CASH":
                continue
            if sym in opens.columns and pd.notna(opens.loc[date, sym]):
                open_prices[sym] = float(opens.loc[date, sym])
        if cash_symbol_resolver is not None and ("CASH" in targets or any(s in state.shares for s in ("SGOV", "BIL"))):
            cash_sym = cash_symbol_resolver(date)
            if cash_sym in opens.columns and pd.notna(opens.loc[date, cash_sym]):
                open_prices[cash_sym] = float(opens.loc[date, cash_sym])

        if bootstrap or date in exec_set:
            tw = dict(targets)
            # Map CASH token to PIT cash ETF
            if "CASH" in tw and cash_symbol_resolver is not None:
                csym = cash_symbol_resolver(date)
                w = tw.pop("CASH")
                tw[csym] = tw.get(csym, 0.0) + w
            # prices for all target symbols
            prices = {}
            missing = False
            for sym in tw:
                if sym not in opens.columns or pd.isna(opens.loc[date, sym]):
                    missing = True
                    all_logs.append(
                        {
                            "asof": str(date.date()),
                            "portfolio_id": portfolio_id,
                            "event": "REBALANCE_SKIP_MISSING_PRICE",
                            "symbol": sym,
                        }
                    )
                else:
                    prices[sym] = float(opens.loc[date, sym])
            # also need prices for current holdings to sell
            for sym in state.shares:
                if sym not in prices and sym in opens.columns and pd.notna(opens.loc[date, sym]):
                    prices[sym] = float(opens.loc[date, sym])
            if not missing or prices:
                state, logs, _ = execute_rebalance(
                    state,
                    target_weights=tw,
                    prices=prices,
                    cfg=cfg,
                    asof=date,
                    portfolio_id=portfolio_id,
                )
                all_logs.extend(logs)
            bootstrap = False

        close_prices = {}
        for sym in state.shares:
            if sym in closes.columns and pd.notna(closes.loc[date, sym]):
                close_prices[sym] = float(closes.loc[date, sym])
        nav = mark_to_market(state, close_prices)
        ret = 0.0 if prev_nav is None or prev_nav <= 0 else nav / prev_nav - 1
        equity_rows.append({"date": date, "net_return": ret, "nav": nav, "cash": state.cash})
        prev_nav = nav

    eq = pd.DataFrame(equity_rows).set_index("date")
    if len(eq) and eq["nav"].iloc[0] > 0:
        eq["equity_net"] = eq["nav"] / eq["nav"].iloc[0]
    else:
        eq["equity_net"] = 1.0
    return {"equity": eq, "logs": all_logs, "final_state": asdict(state), "portfolio_id": portfolio_id}


def write_paper_logs(directory: Path, run: dict[str, Any]) -> None:
    pid = run["portfolio_id"]
    run["equity"].to_csv(directory / f"paper_{pid}_equity.csv")
    pd.DataFrame(run["logs"]).to_csv(directory / f"paper_{pid}_audit_log.csv", index=False)
    (directory / f"paper_{pid}_final_state.json").write_text(
        json.dumps(run["final_state"], indent=2, default=str), encoding="utf-8"
    )
