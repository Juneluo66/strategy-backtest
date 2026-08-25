"""Weekly v1 live: signal → IBKR rebalance → NAV ledger → optional git push."""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import ProjectConfig
from .data import load_adj_close
from .ibkr_client import (
    AccountSnapshot,
    connect_ib,
    disconnect_ib,
    fetch_account_snapshot,
)
from .ibkr_config import IbkrLiveConfig
from .live_ledger import (
    append_live_row,
    load_initial_nav,
    set_initial_nav,
    write_performance_report,
    _read_ledger,
)
from .oos_ledger import generate_oos_candidates


def _current_week_id() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _latest_signal(cfg: IbkrLiveConfig) -> tuple[int, str, dict]:
    """Reuse frozen OOS candidate generator for current BTC signal."""
    proj = ProjectConfig()
    cand = generate_oos_candidates(proj)
    if cand.empty:
        raise RuntimeError("No OOS candidates — check BTC data and calendar")
    # Prefer incomplete week (no strategy_return) or latest week
    pending = cand[cand["strategy_return"].isna()]
    row = pending.iloc[0] if len(pending) else cand.iloc[-1]
    sig = int(row["signal"])
    target = str(row["target"])
    return sig, target, row.to_dict()


def _weekly_return_from_ledger(cfg: IbkrLiveConfig, nav: float) -> Optional[float]:
    path = cfg.ledger_path()
    df = _read_ledger(path)
    if df.empty:
        return None
    prev = float(df.iloc[-1]["net_liquidation"])
    if prev <= 0:
        return None
    return nav / prev - 1.0


def rebalance_to_target(
    ib: Any,
    cfg: IbkrLiveConfig,
    target: str,
    *,
    dry_run: bool,
) -> str:
    from ib_insync import Stock

    strat = cfg.raw["strategy"]
    sym = strat["risk_on_symbol"] if target == strat["risk_on_symbol"] else strat["risk_off_symbol"]
    other = strat["risk_off_symbol"] if sym == strat["risk_on_symbol"] else strat["risk_on_symbol"]
    pct = float(strat.get("target_pct", 1.0))

    contract = Stock(sym, strat["exchange"], strat["currency"])
    other_contract = Stock(other, strat["exchange"], strat["currency"])
    ib.qualifyContracts(contract, other_contract)

    if dry_run:
        return f"DRY_RUN target={sym} {pct*100:.0f}%"

    # Flatten other leg then target 100%
    ib.orderTargetPercent(other_contract, 0.0)
    ib.sleep(2)
    trade = ib.orderTargetPercent(contract, pct)
    ib.sleep(3)
    status = trade.orderStatus.status if trade.orderStatus else "unknown"
    return f"orderTargetPercent({sym},{pct}) status={status}"


def run_live_weekly(
    cfg: IbkrLiveConfig,
    *,
    dry_run: bool = False,
    skip_trade: bool = False,
    git_push: bool = False,
    force_initial_nav: bool = False,
) -> dict[str, Any]:
    if not cfg.raw.get("enabled", True):
        return {"status": "disabled"}

    sig, target, sig_row = _latest_signal(cfg)
    week_id = str(sig_row.get("week_id", _current_week_id()))

    ib = connect_ib(cfg)
    try:
        snap = fetch_account_snapshot(ib, cfg)
        init_path = cfg.initial_nav_path()
        init_doc = load_initial_nav(init_path)
        if init_doc is None or force_initial_nav:
            init_doc = set_initial_nav(
                init_path,
                snap.net_liquidation,
                snap.account_id,
                note="auto_baseline_on_first_connect",
            )
        initial_nav = float(init_doc["initial_nav"])

        order_note = "skip_trade"
        executed = False
        if not skip_trade:
            order_note = rebalance_to_target(ib, cfg, target, dry_run=dry_run)
            executed = not dry_run and "DRY_RUN" not in order_note
            if not dry_run:
                snap = fetch_account_snapshot(ib, cfg)

        weekly_ret = _weekly_return_from_ledger(cfg, snap.net_liquidation)
        row_result = append_live_row(
            cfg,
            week_id=week_id,
            signal=sig,
            target=target,
            snap=snap,
            initial_nav=initial_nav,
            weekly_return=weekly_ret,
            rebalance_executed=executed,
            order_note=order_note,
        )
        report_path = write_performance_report(cfg)

        git_result = None
        if git_push and cfg.raw.get("git", {}).get("auto_push", True):
            git_result = _git_push_live(cfg, report_path)

        return {
            "status": "ok",
            "week_id": week_id,
            "signal": sig,
            "target": target,
            "snapshot": {
                "net_liquidation": snap.net_liquidation,
                "total_cash": snap.total_cash,
                "qqq_shares": snap.qqq_shares,
                "shy_shares": snap.shy_shares,
            },
            "initial_nav": initial_nav,
            "return_since_start": snap.net_liquidation / initial_nav - 1.0,
            "ledger": row_result,
            "report": str(report_path),
            "order_note": order_note,
            "git": git_result,
            "btc_signal_row": {
                "btc_close": sig_row.get("btc_close"),
                "sma50": sig_row.get("sma50"),
                "mom20": sig_row.get("mom20"),
            },
        }
    finally:
        disconnect_ib(ib)


def run_live_status(cfg: IbkrLiveConfig) -> dict[str, Any]:
    ib = connect_ib(cfg)
    try:
        snap = fetch_account_snapshot(ib, cfg)
        init = load_initial_nav(cfg.initial_nav_path())
        initial_nav = float(init["initial_nav"]) if init else None
        ret = None
        if initial_nav:
            ret = snap.net_liquidation / initial_nav - 1.0
        sig, target, _ = _latest_signal(cfg)
        return {
            "connected": True,
            "account_id": snap.account_id,
            "net_liquidation": snap.net_liquidation,
            "total_cash": snap.total_cash,
            "buying_power": snap.buying_power,
            "qqq_shares": snap.qqq_shares,
            "shy_shares": snap.shy_shares,
            "initial_nav": initial_nav,
            "return_since_start": ret,
            "current_signal": sig,
            "current_target": target,
            "mode": cfg.raw.get("mode"),
        }
    finally:
        disconnect_ib(ib)


def _git_push_live(cfg: IbkrLiveConfig, report_path: Path) -> dict[str, Any]:
    root = cfg.project_root.parent  # strategy-backtest monorepo root
    prefix = cfg.raw.get("git", {}).get("commit_prefix", "live(v1):")
    week = _current_week_id()
    paths = [
        cfg.ledger_path(),
        cfg.initial_nav_path(),
        report_path,
    ]
    rel_paths = []
    for p in paths:
        try:
            rel_paths.append(str(p.relative_to(root)))
        except ValueError:
            rel_paths.append(str(p))

    cmds = [
        ["git", "add", *rel_paths],
        [
            "git",
            "commit",
            "-m",
            f"{prefix} weekly update {week}",
            "--allow-empty",
        ],
        ["git", "push", "origin", "main"],
    ]
    outputs = []
    for cmd in cmds:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        outputs.append({"cmd": cmd, "code": proc.returncode, "out": proc.stdout[-500:], "err": proc.stderr[-500:]})
        if proc.returncode != 0 and cmd[1] != "commit":
            break
    return {"repo": str(root), "steps": outputs}
