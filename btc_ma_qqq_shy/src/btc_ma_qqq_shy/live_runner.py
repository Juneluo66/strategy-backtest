"""Weekly v1 live: signal → IBKR rebalance → NAV ledger → optional git push."""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .capital_pool import (
    CapitalPoolState,
    compute_pool_nav,
    init_pool_from_cash,
    inject_capital,
    load_pool_state,
    save_pool_state,
)
from .config import ProjectConfig
from .ibkr_client import (
    build_order_plan,
    connect_ib,
    disconnect_ib,
    execute_order_plan,
    fetch_account_snapshot,
    fetch_etf_prices,
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
    proj = ProjectConfig(project_root=cfg.project_root)
    cand = generate_oos_candidates(proj)
    if cand.empty:
        raise RuntimeError("No OOS candidates — check BTC data and calendar")
    pending = cand[cand["strategy_return"].isna()]
    row = pending.iloc[0] if len(pending) else cand.iloc[-1]
    sig = int(row["signal"])
    target = str(row["target"])
    return sig, target, row.to_dict()


def _weekly_return_from_ledger(cfg: IbkrLiveConfig, pool_nav: float) -> Optional[float]:
    path = cfg.ledger_path()
    df = _read_ledger(path)
    if df.empty:
        return None
    prev = float(df.iloc[-1]["pool_nav"])
    if prev <= 0:
        return None
    return pool_nav / prev - 1.0


def _sync_initial_nav(cfg: IbkrLiveConfig, pool: CapitalPoolState) -> dict:
    return set_initial_nav(
        cfg.initial_nav_path(),
        pool.total_capital_basis,
        pool.account_id,
        note="locked_cash_capital_pool",
    )


def _pool_snapshot(
    cfg: IbkrLiveConfig,
    pool: CapitalPoolState,
    prices: dict[str, float],
) -> dict[str, Any]:
    qqq_sym = cfg.raw["strategy"]["risk_on_symbol"]
    shy_sym = cfg.raw["strategy"]["risk_off_symbol"]
    pool_nav = compute_pool_nav(
        pool,
        qqq_price=prices[qqq_sym],
        shy_price=prices[shy_sym],
    )
    basis = pool.total_capital_basis
    return {
        "initial_capital": pool.initial_capital,
        "injected_capital": pool.injected_capital,
        "total_capital_basis": basis,
        "pool_nav": pool_nav,
        "return_since_start": pool_nav / basis - 1.0 if basis > 0 else 0.0,
        "qqq_shares": pool.qqq_shares,
        "shy_shares": pool.shy_shares,
        "strategy_cash": pool.strategy_cash,
        "locked": pool.locked,
        "set_utc": pool.set_utc,
    }


def run_live_preview(
    cfg: IbkrLiveConfig,
    *,
    capital_amount: Optional[float] = None,
) -> dict[str, Any]:
    """Read-only: account cash, pool state, signal, and planned orders."""
    sig, target, sig_row = _latest_signal(cfg)
    ib = connect_ib(cfg)
    try:
        snap = fetch_account_snapshot(ib, cfg)
        prices = fetch_etf_prices(ib, cfg)
        pool = load_pool_state(cfg)

        proposed_capital = capital_amount
        if pool is None:
            proposed_capital = proposed_capital if proposed_capital is not None else snap.total_cash
        else:
            proposed_capital = pool.total_capital_basis

        order_plan = None
        pool_nav = None
        if pool is not None:
            pool_nav = compute_pool_nav(
                pool,
                qqq_price=prices[cfg.raw["strategy"]["risk_on_symbol"]],
                shy_price=prices[cfg.raw["strategy"]["risk_off_symbol"]],
            )
            order_plan = build_order_plan(cfg, pool, target=target, **{
                "qqq_price": prices[cfg.raw["strategy"]["risk_on_symbol"]],
                "shy_price": prices[cfg.raw["strategy"]["risk_off_symbol"]],
            }).to_dict()

        return {
            "status": "preview",
            "requires_confirmation": True,
            "account": {
                "account_id": snap.account_id,
                "net_liquidation": snap.net_liquidation,
                "total_cash": snap.total_cash,
                "buying_power": snap.buying_power,
                "qqq_shares_account": snap.qqq_shares,
                "shy_shares_account": snap.shy_shares,
            },
            "capital": {
                "pool_initialized": pool is not None,
                "proposed_lock_amount": proposed_capital,
                "available_cash": snap.total_cash,
                "pool": _pool_snapshot(cfg, pool, prices) if pool else None,
            },
            "signal": {
                "week_id": sig_row.get("week_id"),
                "signal": sig,
                "target": target,
                "btc_close": sig_row.get("btc_close"),
                "sma50": sig_row.get("sma50"),
                "mom20": sig_row.get("mom20"),
            },
            "order_plan": order_plan,
            "next_steps": _preview_next_steps(pool, proposed_capital, snap.total_cash),
        }
    finally:
        disconnect_ib(ib)


def _preview_next_steps(
    pool: Optional[CapitalPoolState],
    proposed_capital: Optional[float],
    available_cash: float,
) -> list[str]:
    steps: list[str] = []
    if pool is None:
        steps.append(
            f"Confirm capital lock (proposed ${proposed_capital:,.2f}; account cash ${available_cash:,.2f})."
        )
        steps.append("Then run: btc-ma-qqq live-init --capital <AMOUNT> --confirm")
    else:
        steps.append("Capital pool already locked.")
    steps.append("To trade: btc-ma-qqq live-weekly --confirm")
    steps.append("Dry-run first: btc-ma-qqq live-weekly --dry-run")
    return steps


def run_live_init(
    cfg: IbkrLiveConfig,
    *,
    capital_amount: Optional[float] = None,
    confirm: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    ib = connect_ib(cfg)
    try:
        snap = fetch_account_snapshot(ib, cfg)
        amount = capital_amount if capital_amount is not None else snap.total_cash
        preview = {
            "account_id": snap.account_id,
            "available_cash": snap.total_cash,
            "proposed_lock_amount": amount,
            "net_liquidation": snap.net_liquidation,
        }
        if not confirm:
            return {
                "status": "awaiting_confirmation",
                "message": "No capital locked. Re-run with --confirm after you approve the amount.",
                "preview": preview,
            }
        if amount <= 0:
            raise ValueError("capital amount must be positive")
        if amount > snap.total_cash + 0.01:
            raise ValueError(
                f"Requested ${amount:,.2f} exceeds account cash ${snap.total_cash:,.2f}"
            )

        pool = init_pool_from_cash(
            cfg,
            cash_amount=amount,
            account_id=snap.account_id,
            note="user_confirmed_cash_lock",
            overwrite=force,
        )
        init_doc = _sync_initial_nav(cfg, pool)
        prices = fetch_etf_prices(ib, cfg)
        return {
            "status": "initialized",
            "locked_capital": amount,
            "pool": _pool_snapshot(cfg, pool, prices),
            "initial_nav": init_doc,
            "message": "Capital pool locked. Run live-weekly --confirm to deploy/rebalance.",
        }
    finally:
        disconnect_ib(ib)


def run_live_inject(
    cfg: IbkrLiveConfig,
    amount: float,
    *,
    confirm: bool = False,
    note: str = "user_confirmed_injection",
) -> dict[str, Any]:
    ib = connect_ib(cfg)
    try:
        snap = fetch_account_snapshot(ib, cfg)
        pool = load_pool_state(cfg)
        if pool is None:
            raise RuntimeError("No capital pool. Run live-init first.")
        preview = {
            "account_id": snap.account_id,
            "available_cash": snap.total_cash,
            "inject_amount": amount,
            "pool_nav_before_basis": pool.total_capital_basis,
            "pool_nav_after_basis": pool.total_capital_basis + amount,
        }
        if not confirm:
            return {
                "status": "awaiting_confirmation",
                "message": "Re-run with --confirm to add capital to the strategy pool.",
                "preview": preview,
            }
        if amount > snap.total_cash + 0.01:
            raise ValueError(
                f"Injection ${amount:,.2f} exceeds account cash ${snap.total_cash:,.2f}"
            )
        pool = inject_capital(cfg, amount, note=note)
        _sync_initial_nav(cfg, pool)
        prices = fetch_etf_prices(ib, cfg)
        return {
            "status": "injected",
            "injected_amount": amount,
            "pool": _pool_snapshot(cfg, pool, prices),
        }
    finally:
        disconnect_ib(ib)


def run_live_weekly(
    cfg: IbkrLiveConfig,
    *,
    dry_run: bool = False,
    skip_trade: bool = False,
    git_push: bool = False,
    confirm: bool = False,
    force_initial_nav: bool = False,
) -> dict[str, Any]:
    if not cfg.raw.get("enabled", True):
        return {"status": "disabled"}

    require_confirm = bool(
        cfg.raw.get("capital_pool", {}).get("require_confirm_before_trade", True)
    )
    sig, target, sig_row = _latest_signal(cfg)
    week_id = str(sig_row.get("week_id", _current_week_id()))

    ib = connect_ib(cfg)
    try:
        snap = fetch_account_snapshot(ib, cfg)
        prices = fetch_etf_prices(ib, cfg)
        qqq_sym = cfg.raw["strategy"]["risk_on_symbol"]
        shy_sym = cfg.raw["strategy"]["risk_off_symbol"]

        pool = load_pool_state(cfg)
        if pool is None:
            return {
                "status": "error",
                "error": "No locked capital pool. Run live-init --capital <AMOUNT> --confirm first.",
                "preview_hint": "Run live-preview to see available cash and proposed lock.",
            }

        if force_initial_nav:
            _sync_initial_nav(cfg, pool)

        init_doc = load_initial_nav(cfg.initial_nav_path())
        capital_basis = float(init_doc["initial_nav"]) if init_doc else pool.total_capital_basis

        pool_nav = compute_pool_nav(
            pool,
            qqq_price=prices[qqq_sym],
            shy_price=prices[shy_sym],
        )
        plan = build_order_plan(
            cfg,
            pool,
            target=target,
            qqq_price=prices[qqq_sym],
            shy_price=prices[shy_sym],
        )

        if not skip_trade and require_confirm and not confirm and not dry_run:
            return {
                "status": "awaiting_confirmation",
                "message": "Orders blocked until you confirm. Re-run with --confirm.",
                "week_id": week_id,
                "signal": sig,
                "target": target,
                "capital": {
                    "locked_basis": capital_basis,
                    "pool_nav": pool_nav,
                    "return_since_start": pool_nav / capital_basis - 1.0 if capital_basis > 0 else 0.0,
                },
                "order_plan": plan.to_dict(),
                "account_cash": snap.total_cash,
            }

        order_note = "skip_trade"
        executed = False
        if not skip_trade:
            order_note, pool = execute_order_plan(
                ib, cfg, pool, plan, dry_run=dry_run
            )
            executed = not dry_run and "DRY_RUN" not in order_note
            if not dry_run and executed:
                pool_nav = compute_pool_nav(
                    pool,
                    qqq_price=prices[qqq_sym],
                    shy_price=prices[shy_sym],
                )

        weekly_ret = _weekly_return_from_ledger(cfg, pool_nav)
        row_result = append_live_row(
            cfg,
            week_id=week_id,
            signal=sig,
            target=target,
            snap=snap,
            pool_nav=pool_nav,
            capital_basis=capital_basis,
            pool=pool,
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
            "capital": {
                "locked_basis": capital_basis,
                "pool_nav": pool_nav,
                "return_since_start": pool_nav / capital_basis - 1.0 if capital_basis > 0 else 0.0,
                "strategy_cash": pool.strategy_cash,
                "qqq_shares": pool.qqq_shares,
                "shy_shares": pool.shy_shares,
            },
            "account": {
                "net_liquidation": snap.net_liquidation,
                "total_cash": snap.total_cash,
            },
            "order_plan": plan.to_dict(),
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
        prices = fetch_etf_prices(ib, cfg)
        pool = load_pool_state(cfg)
        init = load_initial_nav(cfg.initial_nav_path())
        sig, target, _ = _latest_signal(cfg)

        out: dict[str, Any] = {
            "connected": True,
            "account_id": snap.account_id,
            "net_liquidation": snap.net_liquidation,
            "total_cash": snap.total_cash,
            "buying_power": snap.buying_power,
            "qqq_shares_account": snap.qqq_shares,
            "shy_shares_account": snap.shy_shares,
            "current_signal": sig,
            "current_target": target,
            "mode": cfg.raw.get("mode"),
            "pool_initialized": pool is not None,
        }
        if pool is not None:
            basis = pool.total_capital_basis
            pool_nav = compute_pool_nav(
                pool,
                qqq_price=prices[cfg.raw["strategy"]["risk_on_symbol"]],
                shy_price=prices[cfg.raw["strategy"]["risk_off_symbol"]],
            )
            out["capital_pool"] = _pool_snapshot(cfg, pool, prices)
            out["return_since_start"] = pool_nav / basis - 1.0 if basis > 0 else 0.0
        if init:
            out["initial_nav_record"] = init
        return out
    finally:
        disconnect_ib(ib)


def _git_push_live(cfg: IbkrLiveConfig, report_path: Path) -> dict[str, Any]:
    root = cfg.project_root.parent
    prefix = cfg.raw.get("git", {}).get("commit_prefix", "live(v1):")
    week = _current_week_id()
    paths = [
        cfg.ledger_path(),
        cfg.initial_nav_path(),
        report_path,
        cfg.project_root / cfg.raw.get("capital_pool", {}).get(
            "state_path", "reports/live/capital_pool.json"
        ),
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
        outputs.append(
            {"cmd": cmd, "code": proc.returncode, "out": proc.stdout[-500:], "err": proc.stderr[-500:]}
        )
        if proc.returncode != 0 and cmd[1] != "commit":
            break
    return {"repo": str(root), "steps": outputs}
