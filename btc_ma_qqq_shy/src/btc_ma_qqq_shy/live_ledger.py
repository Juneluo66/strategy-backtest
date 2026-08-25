"""Append-only live NAV ledger for IBKR v1 tracking."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from .ibkr_client import AccountSnapshot
from .ibkr_config import IbkrLiveConfig

LEDGER_COLUMNS = [
    "week_id",
    "recorded_utc",
    "mode",
    "account_id",
    "rule_id",
    "signal",
    "target",
    "net_liquidation",
    "total_cash",
    "buying_power",
    "qqq_shares",
    "shy_shares",
    "qqq_mkt_value",
    "shy_mkt_value",
    "initial_nav",
    "nav_return_since_start",
    "weekly_nav_return",
    "rebalance_executed",
    "order_note",
]


def _read_ledger(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    df = pd.read_csv(path)
    for c in LEDGER_COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA
    return df[LEDGER_COLUMNS]


def load_initial_nav(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def set_initial_nav(path: Path, nav: float, account_id: str, note: str = "") -> dict:
    payload = {
        "initial_nav": nav,
        "account_id": account_id,
        "set_utc": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return payload


def append_live_row(
    cfg: IbkrLiveConfig,
    *,
    week_id: str,
    signal: int,
    target: str,
    snap: AccountSnapshot,
    initial_nav: float,
    weekly_return: Optional[float],
    rebalance_executed: bool,
    order_note: str,
) -> dict[str, Any]:
    path = cfg.ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_ledger(path)
    if week_id in existing["week_id"].astype(str).tolist():
        return {"appended": False, "reason": "week_exists", "week_id": week_id}

    nav = snap.net_liquidation
    ret = (nav / initial_nav - 1.0) if initial_nav > 0 else 0.0
    row = {
        "week_id": week_id,
        "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": cfg.raw.get("mode", "paper"),
        "account_id": snap.account_id,
        "rule_id": cfg.raw["strategy"]["rule_id"],
        "signal": signal,
        "target": target,
        "net_liquidation": nav,
        "total_cash": snap.total_cash,
        "buying_power": snap.buying_power,
        "qqq_shares": snap.qqq_shares,
        "shy_shares": snap.shy_shares,
        "qqq_mkt_value": snap.qqq_mkt_value,
        "shy_mkt_value": snap.shy_mkt_value,
        "initial_nav": initial_nav,
        "nav_return_since_start": ret,
        "weekly_nav_return": weekly_return if weekly_return is not None else "",
        "rebalance_executed": rebalance_executed,
        "order_note": order_note,
    }
    out = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    out.to_csv(path, index=False)
    return {"appended": True, "week_id": week_id, "nav": nav, "return_since_start": ret}


def render_performance_md(cfg: IbkrLiveConfig) -> str:
    path = cfg.ledger_path()
    init_path = cfg.initial_nav_path()
    df = _read_ledger(path)
    init = load_initial_nav(init_path) or {}
    lines = [
        "# v1 Live Performance (IBKR)",
        "",
        f"Rule: `{cfg.raw['strategy']['rule_id']}`",
        f"Mode: `{cfg.raw.get('mode')}`",
        "",
    ]
    if init:
        lines += [
            f"Initial NAV (baseline): **${init.get('initial_nav', 0):,.2f}**",
            f"Set at: `{init.get('set_utc', '')}`",
            "",
        ]
    if df.empty:
        lines.append("_No ledger rows yet._")
        return "\n".join(lines)

    last = df.iloc[-1]
    lines += [
        f"Latest week: `{last['week_id']}`",
        f"Current NAV: **${float(last['net_liquidation']):,.2f}**",
        f"Return since start: **{100*float(last['nav_return_since_start']):.2f}%**",
        f"Target: `{last['target']}` (signal={last['signal']})",
        "",
        "## Weekly ledger",
        "",
        "| Week | NAV | Weekly | Since start | Target | Cash | Note |",
        "|---|---:|---:|---:|---|---:|---|",
    ]
    for _, r in df.iterrows():
        wr = r["weekly_nav_return"]
        wr_s = f"{100*float(wr):.2f}%" if pd.notna(wr) and str(wr) != "" else "—"
        lines.append(
            f"| {r['week_id']} | ${float(r['net_liquidation']):,.2f} | {wr_s} | "
            f"{100*float(r['nav_return_since_start']):.2f}% | {r['target']} | "
            f"${float(r['total_cash']):,.0f} | {str(r['order_note'])[:40]} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_performance_report(cfg: IbkrLiveConfig) -> Path:
    md = render_performance_md(cfg)
    out = cfg.report_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    return out
