"""Manual fill / pending-order bookkeeping (user syncs; no IBKR API)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from .capital_pool import compute_pool_nav, load_pool_state, save_pool_state
from .ibkr_config import IbkrLiveConfig
from .live_ledger import LEDGER_COLUMNS, _read_ledger, write_performance_report

FILL_COLUMNS = [
    "recorded_utc",
    "fill_time_utc",
    "week_id",
    "status",
    "side",
    "symbol",
    "shares",
    "avg_price",
    "cost_basis_per_share",
    "notional",
    "fee",
    "order_id",
    "limit_price",
    "tif",
    "note",
    "source",
]


def _fills_path(cfg: IbkrLiveConfig) -> Path:
    return cfg.project_root / "reports" / "live" / "fills.csv"


def _pending_path(cfg: IbkrLiveConfig) -> Path:
    return cfg.project_root / "reports" / "live" / "pending_order.json"


def _read_fills(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=FILL_COLUMNS)
    df = pd.read_csv(path)
    for c in FILL_COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA
    return df[FILL_COLUMNS]


def _append_fill_row(cfg: IbkrLiveConfig, row: dict[str, Any]) -> Path:
    path = _fills_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = _read_fills(path)
    out = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    out.to_csv(path, index=False)
    return path


def run_live_record_pending(
    cfg: IbkrLiveConfig,
    *,
    symbol: str,
    side: str,
    shares: float,
    limit_price: float,
    order_id: str = "",
    tif: str = "DAY",
    week_id: str = "",
    note: str = "",
) -> dict[str, Any]:
    """Record a user-placed pending order (not yet filled)."""
    from .live_runner import _latest_signal, _current_week_id

    if not week_id:
        try:
            _, _, sig_row = _latest_signal(cfg)
            week_id = str(sig_row.get("week_id", _current_week_id()))
        except Exception:
            week_id = _current_week_id()

    payload = {
        "status": "pending",
        "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "week_id": week_id,
        "side": side.upper(),
        "symbol": symbol.upper(),
        "shares": float(shares),
        "limit_price": float(limit_price),
        "order_id": order_id,
        "tif": tif,
        "note": note or "user_reported_pending",
        "source": "user_sync",
        "account_id": "U17832073",
    }
    path = _pending_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    _append_fill_row(
        cfg,
        {
            "recorded_utc": payload["recorded_utc"],
            "week_id": week_id,
            "status": "pending",
            "side": payload["side"],
            "symbol": payload["symbol"],
            "shares": payload["shares"],
            "avg_price": "",
            "notional": "",
            "order_id": order_id,
            "limit_price": limit_price,
            "tif": tif,
            "note": payload["note"],
            "source": "user_sync",
        },
    )
    return {"status": "pending_recorded", "pending": payload, "path": str(path)}


def run_live_record_fill(
    cfg: IbkrLiveConfig,
    *,
    symbol: str,
    side: str,
    shares: float,
    avg_price: float,
    week_id: str = "",
    order_id: str = "",
    fee: float = 0.0,
    fill_time_utc: str = "",
    note: str = "",
    confirm: bool = False,
) -> dict[str, Any]:
    """Book an actual fill into the capital pool + ledger. No IBKR contact."""
    from .live_runner import _latest_signal, _current_week_id

    pool = load_pool_state(cfg)
    if pool is None:
        raise RuntimeError("No capital pool. Run live-init first (local lock only).")

    symbol = symbol.upper()
    side = side.upper()
    shares = float(shares)
    avg_price = float(avg_price)
    fee = max(float(fee), 0.0)
    if shares <= 0 or avg_price <= 0:
        raise ValueError("shares and avg_price must be positive")
    if symbol not in ("QQQ", "SHY"):
        raise ValueError("symbol must be QQQ or SHY")
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")

    if not week_id:
        try:
            _, _, sig_row = _latest_signal(cfg)
            week_id = str(sig_row.get("week_id", _current_week_id()))
        except Exception:
            week_id = _current_week_id()

    notional = round(shares * avg_price, 4)
    total_cost = round(notional + fee, 4) if side == "BUY" else notional
    cost_basis_per_share = round(total_cost / shares, 6) if side == "BUY" and shares > 0 else 0.0
    preview = {
        "week_id": week_id,
        "side": side,
        "symbol": symbol,
        "shares": shares,
        "avg_price": avg_price,
        "cost_basis_per_share": cost_basis_per_share,
        "notional": notional,
        "fee": fee,
        "total_cost": total_cost,
        "order_id": order_id,
        "fill_time_utc": fill_time_utc or None,
        "pool_before": {
            "cash": pool.strategy_cash,
            "qqq": pool.qqq_shares,
            "shy": pool.shy_shares,
        },
    }
    if not confirm:
        return {
            "status": "awaiting_confirmation",
            "message": "Re-run with --confirm to book this actual fill.",
            "preview": preview,
        }

    if side == "BUY":
        if symbol == "QQQ":
            old_sh, old_cb = pool.qqq_shares, pool.qqq_cost_basis_per_share
            pool.qqq_shares = old_sh + shares
            pool.qqq_cost_basis_per_share = (
                (old_sh * old_cb + total_cost) / pool.qqq_shares
                if pool.qqq_shares > 0
                else cost_basis_per_share
            )
        else:
            old_sh, old_cb = pool.shy_shares, pool.shy_cost_basis_per_share
            pool.shy_shares = old_sh + shares
            pool.shy_cost_basis_per_share = (
                (old_sh * old_cb + total_cost) / pool.shy_shares
                if pool.shy_shares > 0
                else cost_basis_per_share
            )
        pool.strategy_cash = max(pool.strategy_cash - total_cost, 0.0)
        pool.fees_paid_total += fee
    else:
        held = pool.qqq_shares if symbol == "QQQ" else pool.shy_shares
        if shares > held + 1e-9:
            raise ValueError(f"Sell {shares} {symbol} but pool only holds {held}")
        if symbol == "QQQ":
            pool.qqq_shares = max(pool.qqq_shares - shares, 0.0)
            if pool.qqq_shares <= 1e-12:
                pool.qqq_shares = 0.0
                pool.qqq_cost_basis_per_share = 0.0
        else:
            pool.shy_shares = max(pool.shy_shares - shares, 0.0)
            if pool.shy_shares <= 1e-12:
                pool.shy_shares = 0.0
                pool.shy_cost_basis_per_share = 0.0
        pool.strategy_cash += notional - fee
        pool.fees_paid_total += fee

    save_pool_state(cfg, pool)

    # Clear pending if matches
    pending_path = _pending_path(cfg)
    if pending_path.exists():
        pending_path.unlink()

    recorded_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fill_ts = fill_time_utc or recorded_utc
    fill_path = _append_fill_row(
        cfg,
        {
            "recorded_utc": recorded_utc,
            "fill_time_utc": fill_ts,
            "week_id": week_id,
            "status": "filled",
            "side": side,
            "symbol": symbol,
            "shares": shares,
            "avg_price": avg_price,
            "cost_basis_per_share": cost_basis_per_share,
            "notional": notional,
            "fee": fee,
            "order_id": order_id,
            "limit_price": "",
            "tif": "",
            "note": note or "user_reported_fill",
            "source": "user_sync",
        },
    )

    qqq_px = avg_price if symbol == "QQQ" else (_last_symbol_price(cfg, "QQQ") or 0.0)
    shy_px = avg_price if symbol == "SHY" else (_last_symbol_price(cfg, "SHY") or 0.0)
    if pool.qqq_shares > 0 and qqq_px <= 0:
        qqq_px = pool.qqq_cost_basis_per_share or 0.0
    if pool.shy_shares > 0 and shy_px <= 0:
        shy_px = pool.shy_cost_basis_per_share or 0.0
    pool_nav = compute_pool_nav(pool, qqq_price=qqq_px, shy_price=shy_px)
    book_nav = pool.book_cost_nav()

    basis = pool.total_capital_basis
    ret = pool_nav / basis - 1.0 if basis > 0 else 0.0
    ledger_path = cfg.ledger_path()
    existing = _read_ledger(ledger_path)
    signal = 0
    target = symbol
    try:
        signal, target, _ = _latest_signal(cfg)
    except Exception:
        pass

    # Weekly return vs previous ledger row
    weekly_ret = None
    if not existing.empty:
        try:
            prev = float(existing.iloc[-1]["pool_nav"])
            if prev > 0:
                weekly_ret = pool_nav / prev - 1.0
        except (TypeError, ValueError):
            weekly_ret = None

    row = {
        "week_id": week_id,
        "recorded_utc": recorded_utc,
        "mode": "live_manual",
        "account_id": pool.account_id,
        "rule_id": cfg.raw["strategy"]["rule_id"],
        "signal": signal,
        "target": target,
        "pool_nav": pool_nav,
        "capital_basis": basis,
        "strategy_cash": pool.strategy_cash,
        "pool_qqq_shares": pool.qqq_shares,
        "pool_shy_shares": pool.shy_shares,
        "account_net_liquidation": "",
        "account_total_cash": "",
        "buying_power": "",
        "nav_return_since_start": ret,
        "weekly_nav_return": weekly_ret if weekly_ret is not None else "",
        "rebalance_executed": True,
        "order_note": (
            f"USER_FILL {side} {shares} {symbol} @ {avg_price}"
            + f" cost_basis={cost_basis_per_share:.4f}"
            + (f" fee={fee}" if fee else "")
            + (f" order={order_id}" if order_id else "")
            + (f" fill={fill_ts}" if fill_ts else "")
            + (f" {note}" if note else "")
        ),
    }
    # Allow multiple fill rows per week — do not skip if week exists
    out = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    for c in LEDGER_COLUMNS:
        if c not in out.columns:
            out[c] = pd.NA
    out[LEDGER_COLUMNS].to_csv(ledger_path, index=False)
    report = write_performance_report(cfg)

    return {
        "status": "filled_recorded",
        "fill": preview,
        "pool": {
            "strategy_cash": pool.strategy_cash,
            "qqq_shares": pool.qqq_shares,
            "shy_shares": pool.shy_shares,
            "qqq_cost_basis_per_share": pool.qqq_cost_basis_per_share,
            "shy_cost_basis_per_share": pool.shy_cost_basis_per_share,
            "fees_paid_total": pool.fees_paid_total,
            "pool_nav_mark": pool_nav,
            "pool_nav_cost_basis": book_nav,
            "return_since_start": ret,
        },
        "fills_csv": str(fill_path),
        "ledger": str(ledger_path),
        "report": str(report),
    }


def _last_symbol_price(cfg: IbkrLiveConfig, symbol: str) -> Optional[float]:
    df = _read_fills(_fills_path(cfg))
    if df.empty:
        return None
    hit = df[(df["symbol"] == symbol) & (df["status"] == "filled") & (df["avg_price"].notna())]
    if hit.empty:
        return None
    try:
        return float(hit.iloc[-1]["avg_price"])
    except (TypeError, ValueError):
        return None
