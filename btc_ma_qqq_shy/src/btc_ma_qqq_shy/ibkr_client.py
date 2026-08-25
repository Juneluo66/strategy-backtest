"""IBKR connection helpers (ib_insync). Requires TWS or IB Gateway logged in."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

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


def disconnect_ib(ib: Any) -> None:
    if ib.isConnected():
        ib.disconnect()
