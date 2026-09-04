"""IBKR connection helpers (ib_insync). Requires TWS or IB Gateway logged in."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Optional

from .capital_pool import CapitalPoolState, compute_pool_nav, save_pool_state
from .ibkr_config import IbkrLiveConfig


@dataclass
class AccountSnapshot:
    account_id: str
    net_liquidation: float
    total_cash: float
    buying_power: float
    qqq_shares: float
    shy_shares: float
    qqq_mkt_value: float
    shy_mkt_value: float
    gross_position_value: float
    timestamp_utc: str


@dataclass
class OrderPlan:
    target: str
    pool_nav: float
    qqq_price: float
    shy_price: float
    current_qqq_shares: float
    current_shy_shares: float
    target_qqq_shares: float
    target_shy_shares: float
    sell_symbol: Optional[str]
    sell_shares: float
    buy_symbol: str
    buy_shares: float
    buy_notional: float
    buy_cash_qty: float
    fractional: bool
    strategy_cash_after: float

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "pool_nav": self.pool_nav,
            "qqq_price": self.qqq_price,
            "shy_price": self.shy_price,
            "current_qqq_shares": self.current_qqq_shares,
            "current_shy_shares": self.current_shy_shares,
            "target_qqq_shares": self.target_qqq_shares,
            "target_shy_shares": self.target_shy_shares,
            "sell_symbol": self.sell_symbol,
            "sell_shares": self.sell_shares,
            "buy_symbol": self.buy_symbol,
            "buy_shares": self.buy_shares,
            "buy_notional": self.buy_notional,
            "buy_cash_qty": self.buy_cash_qty,
            "fractional": self.fractional,
            "strategy_cash_after": self.strategy_cash_after,
        }


def _env_override(cfg: IbkrLiveConfig) -> IbkrLiveConfig:
    host = os.environ.get("IBKR_HOST")
    port = os.environ.get("IBKR_PORT")
    client = os.environ.get("IBKR_CLIENT_ID")
    account = os.environ.get("IBKR_ACCOUNT")
    mode = os.environ.get("IBKR_MODE")
    if host:
        cfg.raw["connection"]["host"] = host
    if port:
        cfg.raw["connection"]["port"] = int(port)
    if client:
        cfg.raw["connection"]["client_id"] = int(client)
    if account:
        cfg.raw["account"]["account_id"] = account
    if mode:
        cfg.raw["mode"] = mode
    return cfg


def connect_ib(cfg: IbkrLiveConfig) -> Any:
    try:
        from ib_insync import IB
    except ImportError as exc:
        raise RuntimeError(
            "ib_insync not installed. Run: pip install 'btc-ma-qqq-shy[live]'"
        ) from exc

    cfg = _env_override(cfg)
    conn = cfg.raw["connection"]
    ib = IB()
    ib.connect(
        conn["host"],
        int(conn["port"]),
        clientId=int(conn["client_id"]),
        timeout=int(conn.get("timeout_sec", 30)),
        readonly=bool(conn.get("readonly", False)),
    )
    return ib


def pick_account(ib: Any, cfg: IbkrLiveConfig) -> str:
    want = cfg.raw.get("account", {}).get("account_id") or os.environ.get("IBKR_ACCOUNT", "")
    accounts = ib.managedAccounts()
    if not accounts:
        raise RuntimeError("No IBKR managed accounts returned")
    if want and want in accounts:
        return want
    return accounts[0]


def _tag_value(summary: list, tag: str, account: str) -> float:
    for row in summary:
        if row.tag == tag and row.account == account and row.currency == "USD":
            try:
                return float(row.value)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def fetch_account_snapshot(ib: Any, cfg: IbkrLiveConfig) -> AccountSnapshot:
    from datetime import datetime, timezone

    account = pick_account(ib, cfg)
    summary = ib.accountSummary(account)
    portfolio = ib.portfolio(account)

    qqq_sym = cfg.raw["strategy"]["risk_on_symbol"]
    shy_sym = cfg.raw["strategy"]["risk_off_symbol"]
    qqq_sh, shy_sh = 0.0, 0.0
    qqq_mv, shy_mv = 0.0, 0.0
    gross = 0.0
    for p in portfolio:
        sym = p.contract.symbol
        mv = float(p.marketValue)
        gross += abs(mv)
        if sym == qqq_sym:
            qqq_sh = float(p.position)
            qqq_mv = mv
        elif sym == shy_sym:
            shy_sh = float(p.position)
            shy_mv = mv

    return AccountSnapshot(
        account_id=account,
        net_liquidation=_tag_value(summary, "NetLiquidation", account),
        total_cash=_tag_value(summary, "TotalCashValue", account),
        buying_power=_tag_value(summary, "BuyingPower", account),
        qqq_shares=qqq_sh,
        shy_shares=shy_sh,
        qqq_mkt_value=qqq_mv,
        shy_mkt_value=shy_mv,
        gross_position_value=gross,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
    )


def _stock_contracts(cfg: IbkrLiveConfig) -> tuple[Any, Any, str, str]:
    from ib_insync import Stock

    strat = cfg.raw["strategy"]
    qqq_sym = strat["risk_on_symbol"]
    shy_sym = strat["risk_off_symbol"]
    qqq = Stock(qqq_sym, strat["exchange"], strat["currency"])
    shy = Stock(shy_sym, strat["exchange"], strat["currency"])
    return qqq, shy, qqq_sym, shy_sym


def fetch_etf_prices(ib: Any, cfg: IbkrLiveConfig) -> dict[str, float]:
    strat = cfg.raw["strategy"]
    qqq_sym = strat["risk_on_symbol"]
    shy_sym = strat["risk_off_symbol"]
    qqq, shy = _stock_contracts(cfg)[:2]
    ib.qualifyContracts(qqq, shy)
    # Prefer delayed/frozen ticks; fall back to last daily close when market is closed.
    ib.reqMarketDataType(3)
    prices: dict[str, float] = {}
    for contract, sym in ((qqq, qqq_sym), (shy, shy_sym)):
        tickers = ib.reqTickers(contract)
        px: Optional[float] = None
        if tickers:
            t = tickers[0]
            for candidate in (t.marketPrice(), t.last, t.close):
                if candidate is not None and not (
                    isinstance(candidate, float) and math.isnan(candidate)
                ) and candidate > 0:
                    px = float(candidate)
                    break
        if px is None:
            bars = ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr="5 D",
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
            )
            if bars:
                px = float(bars[-1].close)
        if px is None or px <= 0:
            raise RuntimeError(f"No usable price for {sym}")
        prices[sym] = px
    return prices


def build_order_plan(
    cfg: IbkrLiveConfig,
    pool: CapitalPoolState,
    *,
    target: str,
    qqq_price: float,
    shy_price: float,
) -> OrderPlan:
    strat = cfg.raw["strategy"]
    qqq_sym = strat["risk_on_symbol"]
    shy_sym = strat["risk_off_symbol"]
    fractional = bool(strat.get("fractional_shares", True))
    min_usd = float(strat.get("min_order_usd", 0.0))

    pool_nav = compute_pool_nav(pool, qqq_price=qqq_price, shy_price=shy_price)
    if min_usd > 0 and pool_nav < min_usd:
        raise RuntimeError(f"Pool NAV ${pool_nav:,.2f} below min_order_usd ${min_usd:,.2f}")
    if pool_nav <= 0:
        raise RuntimeError("Pool NAV must be positive")

    target_sym = qqq_sym if target == qqq_sym else shy_sym
    other_sym = shy_sym if target_sym == qqq_sym else qqq_sym
    target_px = qqq_price if target_sym == qqq_sym else shy_price

    if fractional:
        target_shares = pool_nav / target_px
    else:
        target_shares = float(math.floor(pool_nav / target_px))
        if target_shares <= 0:
            raise RuntimeError(
                f"Pool NAV too small to buy 1 whole share of {target_sym} @ ${target_px:.2f}"
            )

    target_qqq = float(target_shares if target_sym == qqq_sym else 0.0)
    target_shy = float(target_shares if target_sym == shy_sym else 0.0)

    sell_sym: Optional[str] = None
    sell_shares = 0.0
    buy_shares = 0.0
    buy_cash_qty = 0.0

    if other_sym == qqq_sym and pool.qqq_shares > 0:
        sell_sym = qqq_sym
        sell_shares = pool.qqq_shares
    elif other_sym == shy_sym and pool.shy_shares > 0:
        sell_sym = shy_sym
        sell_shares = pool.shy_shares

    if target_sym == qqq_sym:
        delta = target_qqq - pool.qqq_shares
    else:
        delta = target_shy - pool.shy_shares

    if delta > 0:
        if fractional and pool.strategy_cash >= delta * target_px * 0.99:
            buy_cash_qty = min(pool.strategy_cash, delta * target_px)
            buy_shares = buy_cash_qty / target_px if target_px > 0 else 0.0
        else:
            buy_shares = delta
    elif delta < 0:
        sell_sym = target_sym
        sell_shares = abs(delta)

    buy_notional = buy_cash_qty if buy_cash_qty > 0 else buy_shares * target_px
    invested = target_shares * target_px
    cash_after = max(pool_nav - invested, 0.0)

    return OrderPlan(
        target=target_sym,
        pool_nav=pool_nav,
        qqq_price=qqq_price,
        shy_price=shy_price,
        current_qqq_shares=pool.qqq_shares,
        current_shy_shares=pool.shy_shares,
        target_qqq_shares=target_qqq,
        target_shy_shares=target_shy,
        sell_symbol=sell_sym,
        sell_shares=sell_shares,
        buy_symbol=target_sym,
        buy_shares=buy_shares,
        buy_notional=buy_notional,
        buy_cash_qty=buy_cash_qty,
        fractional=fractional,
        strategy_cash_after=cash_after,
    )


def _limit_price(side: str, last: float, cfg: IbkrLiveConfig) -> float:
    """Slightly aggressive limit so DAY orders can fill at US open."""
    strat = cfg.raw["strategy"]
    buy_bps = float(strat.get("limit_buy_cushion_bps", 50)) / 10_000.0
    sell_bps = float(strat.get("limit_sell_cushion_bps", 50)) / 10_000.0
    if side.upper() == "BUY":
        return round(last * (1.0 + buy_bps), 2)
    return round(last * (1.0 - sell_bps), 2)


def _make_order(
    cfg: IbkrLiveConfig,
    *,
    action: str,
    quantity: float,
    last_price: float,
):
    """Build LMT (default) or MKT order; LMT waits for RTH fill."""
    from ib_insync import LimitOrder, MarketOrder

    strat = cfg.raw["strategy"]
    order_type = str(strat.get("order_type", "LMT")).upper()
    tif = str(strat.get("order_tif", "DAY")).upper()
    outside_rth = bool(strat.get("outside_rth", False))
    qty = round(float(quantity), 6)
    if qty <= 0:
        raise ValueError("order quantity must be positive")

    if order_type == "MKT":
        order = MarketOrder(action, qty)
    else:
        limit = _limit_price(action, last_price, cfg)
        order = LimitOrder(action, qty, limit)
        order.tif = tif
        order.outsideRth = outside_rth
    return order


def execute_order_plan(
    ib: Any,
    cfg: IbkrLiveConfig,
    pool: CapitalPoolState,
    plan: OrderPlan,
    *,
    dry_run: bool,
) -> tuple[str, CapitalPoolState]:
    qqq, shy, qqq_sym, shy_sym = _stock_contracts(cfg)
    ib.qualifyContracts(qqq, shy)
    contract_map = {qqq_sym: qqq, shy_sym: shy}

    if dry_run:
        return f"DRY_RUN {plan.to_dict()}", pool

    notes: list[str] = []
    order_type = str(cfg.raw["strategy"].get("order_type", "LMT")).upper()
    filled_ok = True

    def _wait_status(trade: Any, seconds: float = 3.0) -> str:
        ib.sleep(seconds)
        return trade.orderStatus.status if trade.orderStatus else "unknown"

    def _is_bad(status: str) -> bool:
        return status in {"Cancelled", "Inactive", "ApiCancelled"}

    if plan.sell_symbol and plan.sell_shares > 0:
        c = contract_map[plan.sell_symbol]
        last = plan.qqq_price if plan.sell_symbol == qqq_sym else plan.shy_price
        order = _make_order(cfg, action="SELL", quantity=plan.sell_shares, last_price=last)
        trade = ib.placeOrder(c, order)
        status = _wait_status(trade, 2.0)
        limit = getattr(order, "lmtPrice", None)
        notes.append(
            f"SELL {plan.sell_shares:.6f} {plan.sell_symbol} "
            f"type={order_type} lmt={limit} status={status}"
        )
        if _is_bad(status):
            filled_ok = False
        else:
            proceeds = plan.sell_shares * last
            if plan.sell_symbol == qqq_sym:
                pool.qqq_shares = max(pool.qqq_shares - plan.sell_shares, 0.0)
            else:
                pool.shy_shares = max(pool.shy_shares - plan.sell_shares, 0.0)
            pool.strategy_cash += proceeds

    buy_qty = plan.buy_shares
    if buy_qty <= 0 and plan.buy_cash_qty > 0:
        px = plan.qqq_price if plan.buy_symbol == qqq_sym else plan.shy_price
        buy_qty = plan.buy_cash_qty / px if px > 0 else 0.0

    # API path: whole shares only when fractional_shares=false
    if not plan.fractional and buy_qty > 0:
        buy_qty = float(math.floor(buy_qty))

    if buy_qty > 0 and filled_ok:
        c = contract_map[plan.buy_symbol]
        last = plan.qqq_price if plan.buy_symbol == qqq_sym else plan.shy_price
        order = _make_order(cfg, action="BUY", quantity=buy_qty, last_price=last)
        trade = ib.placeOrder(c, order)
        status = _wait_status(trade, 3.0)
        limit = getattr(order, "lmtPrice", None)
        notes.append(
            f"BUY {buy_qty:.6f} {plan.buy_symbol} "
            f"type={order_type} lmt={limit} status={status}"
        )
        if _is_bad(status):
            filled_ok = False
            notes.append("order_rejected_pool_unchanged")
        else:
            if plan.buy_symbol == qqq_sym:
                pool.qqq_shares += buy_qty
            else:
                pool.shy_shares += buy_qty
            pool.strategy_cash = max(pool.strategy_cash - buy_qty * last, 0.0)
            pool.strategy_cash = plan.strategy_cash_after
    elif buy_qty <= 0:
        notes.append("no_buy_shares_affordable")

    if filled_ok and buy_qty > 0:
        pool.strategy_cash = plan.strategy_cash_after
    save_pool_state(cfg, pool)
    return "; ".join(notes) if notes else "no_orders_needed", pool


def disconnect_ib(ib: Any) -> None:
    if ib.isConnected():
        ib.disconnect()
