"""Weekly v1 live: signal → IBKR rebalance → NAV ledger → optional git push."""
from __future__ import annotations

import json
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


def _us_open_trade_window(cfg: IbkrLiveConfig) -> dict[str, Any]:
    """Weekly trade window: Monday after US cash open (ET), DST-aware.

    Beijing wall-clock ≈ Mon 21:30 (EDT) / Mon 22:30 (EST).
    """
    from zoneinfo import ZoneInfo

    sched = cfg.raw.get("schedule", {})
    tz_name = str(sched.get("timezone", "America/New_York"))
    weekday_name = str(sched.get("rebalance_weekday", "Monday"))
    after_h = int(sched.get("rebalance_after_hour", 9))
    after_m = int(sched.get("rebalance_after_minute", 35))
    end_h = int(sched.get("trade_window_end_hour", 11))

    now_et = datetime.now(ZoneInfo(tz_name))
    now_bj = now_et.astimezone(ZoneInfo("Asia/Shanghai"))
    weekday_ok = now_et.strftime("%A") == weekday_name
    minutes = now_et.hour * 60 + now_et.minute
    start_min = after_h * 60 + after_m
    end_min = end_h * 60
    in_window = weekday_ok and start_min <= minutes < end_min
    return {
        "timezone": tz_name,
        "now_et": now_et.isoformat(),
        "now_beijing": now_bj.isoformat(),
        "weekday": now_et.strftime("%A"),
        "required_weekday": weekday_name,
        "window_et": f"{after_h:02d}:{after_m:02d}–{end_h:02d}:00",
        "in_window": in_window,
    }


def _current_week_id() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _latest_signal(cfg: IbkrLiveConfig) -> tuple[int, str, dict]:
    """Current trade signal = most recent OOS week (not a stuck older pending week)."""
    proj = ProjectConfig(project_root=cfg.project_root)
    cand = generate_oos_candidates(proj)
    if cand.empty:
        raise RuntimeError("No OOS candidates — check BTC data and calendar")
    # Always use the latest week_id. Using first incomplete week caused stale
    # Lark pushes when price cache lagged (e.g. still on 2026-08-17 SHY).
    row = cand.iloc[-1]
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
        basis="locked_cash_capital_pool",
    )


def _sync_observe_initial_nav(cfg: IbkrLiveConfig, snap: Any) -> dict:
    return set_initial_nav(
        cfg.initial_nav_path(),
        snap.net_liquidation,
        snap.account_id,
        note="account_observation_baseline",
        basis="account_observation",
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


def run_live_signal(cfg: IbkrLiveConfig, *, refresh: bool = True) -> dict[str, Any]:
    """Compute this week's QQQ/SHY target from BTC rules — no Gateway needed."""
    from .config import ProjectConfig
    from .data import fetch_prices
    from .oos_ledger import append_oos_ledger

    proj = ProjectConfig(project_root=cfg.project_root)
    # Always refresh before notifying so we don't push a stale week.
    fetch_result = fetch_prices(proj, refresh=refresh)
    oos_result = None
    try:
        oos_result = append_oos_ledger(proj, dry_run=False)
    except Exception as exc:  # keep signal even if ledger append fails
        oos_result = {"error": str(exc)}

    sig, target, sig_row = _latest_signal(cfg)
    out = {
        "status": "ok",
        "gateway_required": False,
        "week_id": str(sig_row.get("week_id", _current_week_id())),
        "signal": sig,
        "target": target,
        "btc_close": sig_row.get("btc_close"),
        "sma50": sig_row.get("sma50"),
        "mom20": sig_row.get("mom20"),
        "rule_id": cfg.raw["strategy"]["rule_id"],
        "computed_utc": datetime.now(timezone.utc).isoformat(),
        "trade_window": _us_open_trade_window(cfg),
        "data_refresh": fetch_result,
        "oos_append": oos_result,
    }
    path = cfg.project_root / "reports" / "live" / "pending_signal.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str))
    out["saved_to"] = str(path)
    return out


def _capital_summary_from_local(cfg: IbkrLiveConfig) -> dict[str, Any]:
    """Summarize locked pool + ledger without contacting IBKR."""
    pool = load_pool_state(cfg)
    df = _read_ledger(cfg.ledger_path())
    out: dict[str, Any] = {"pool_initialized": pool is not None}
    if pool is None:
        return out
    out.update(
        {
            "capital_basis": pool.total_capital_basis,
            "strategy_cash": pool.strategy_cash,
            "qqq_shares": pool.qqq_shares,
            "shy_shares": pool.shy_shares,
            "qqq_cost_basis_per_share": pool.qqq_cost_basis_per_share,
            "shy_cost_basis_per_share": pool.shy_cost_basis_per_share,
            "fees_paid_total": pool.fees_paid_total,
            "account_id": pool.account_id,
            "set_utc": pool.set_utc,
        }
    )
    if df.empty:
        out["latest_pool_nav"] = pool.strategy_cash
        out["return_since_start"] = 0.0
        out["last_weekly_return"] = None
        out["last_week_id"] = None
        out["last_order_note"] = ""
        return out
    last = df.iloc[-1]
    out["latest_pool_nav"] = float(last["pool_nav"]) if last["pool_nav"] == last["pool_nav"] else pool.strategy_cash
    try:
        out["return_since_start"] = float(last["nav_return_since_start"])
    except (TypeError, ValueError):
        out["return_since_start"] = None
    wr = last.get("weekly_nav_return", "")
    out["last_weekly_return"] = (
        float(wr) if wr is not None and str(wr) != "" and wr == wr else None
    )
    out["last_week_id"] = str(last.get("week_id", ""))
    out["last_order_note"] = str(last.get("order_note", ""))
    out["last_target"] = str(last.get("target", ""))
    return out


def run_live_notify(
    cfg: IbkrLiveConfig,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Weekly Lark ping: buy target + local capital summary. Never touches IBKR."""
    from zoneinfo import ZoneInfo

    from .lark_notify import (
        format_weekly_notify_text,
        load_lark_env,
        send_lark_text,
    )

    signal = run_live_signal(cfg)
    capital = _capital_summary_from_local(cfg)
    now_bj = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M %Z")
    payload = {
        "status": "ok",
        "ibkr_contacted": False,
        "now_beijing": now_bj,
        "signal": {
            "week_id": signal["week_id"],
            "signal": signal["signal"],
            "target": signal["target"],
            "rule_id": signal["rule_id"],
            "btc_close": signal["btc_close"],
            "sma50": signal["sma50"],
            "mom20": signal["mom20"],
        },
        "capital_summary": capital,
    }
    text = format_weekly_notify_text(payload)
    payload["message_preview"] = text

    out_path = cfg.project_root / "reports" / "live" / "last_lark_notify.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        payload["lark"] = {"sent": False, "dry_run": True}
        out_path.write_text(json.dumps(payload, indent=2, default=str))
        return payload

    env = load_lark_env(cfg.project_root)
    result = send_lark_text(env["webhook"], text, secret=env["secret"])
    payload["lark"] = {"sent": True, "response": result}
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    return payload


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
        if pool is None and proposed_capital is None:
            proposed_capital = None
        elif pool is not None:
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
            "Cash is never auto-locked. To deploy capital: "
            "btc-ma-qqq live-init --capital <AMOUNT> --confirm"
        )
        if proposed_capital is not None:
            steps.append(
                f"Preview lock amount: ${proposed_capital:,.2f} "
                f"(account cash ${available_cash:,.2f})."
            )
    else:
        steps.append("Capital pool already locked.")
    steps.append("Observation only (no trades): btc-ma-qqq live-weekly --skip-trade")
    steps.append("To trade after lock: btc-ma-qqq live-weekly --confirm")
    steps.append("Dry-run orders: btc-ma-qqq live-weekly --dry-run")
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
        if capital_amount is None:
            return {
                "status": "awaiting_confirmation",
                "message": (
                    "Specify --capital <USD> explicitly. Account cash is never auto-locked."
                ),
                "preview": {
                    "account_id": snap.account_id,
                    "available_cash": snap.total_cash,
                    "net_liquidation": snap.net_liquidation,
                },
            }
        amount = capital_amount
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
    ignore_trade_window: bool = False,
) -> dict[str, Any]:
    if not cfg.raw.get("enabled", True):
        return {"status": "disabled"}

    # Trading / 2FA only at US Monday open (unless mid-week manual override).
    window = _us_open_trade_window(cfg)
    if not skip_trade and not ignore_trade_window and not window["in_window"]:
        return {
            "status": "outside_trade_window",
            "message": (
                "Orders/2FA only at US Monday open "
                f"({window['window_et']} {window['timezone']}; "
                f"Beijing ≈ {window['now_beijing']}). "
                "Use --skip-trade to ledger without orders, or "
                "--ignore-trade-window for a mid-week manual run."
            ),
            "trade_window": window,
        }

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
            if not skip_trade:
                return {
                    "status": "error",
                    "error": (
                        "No locked capital pool. Observation only: live-weekly --skip-trade. "
                        "To trade: live-init --capital <AMOUNT> --confirm then live-weekly --confirm."
                    ),
                    "preview_hint": "Run live-preview --capital <AMOUNT> to preview a lock.",
                }
            # Observation bookkeeping — account NAV only, no pool / no orders.
            init_doc = load_initial_nav(cfg.initial_nav_path())
            if init_doc is None or init_doc.get("basis") != "account_observation":
                init_doc = _sync_observe_initial_nav(cfg, snap)
            capital_basis = float(init_doc["initial_nav"])
            pool_nav = snap.net_liquidation
            order_note = "observe_only"
            weekly_ret = _weekly_return_from_ledger(cfg, pool_nav)
            row_result = append_live_row(
                cfg,
                week_id=week_id,
                signal=sig,
                target=target,
                snap=snap,
                pool_nav=pool_nav,
                capital_basis=capital_basis,
                pool=None,
                weekly_return=weekly_ret,
                rebalance_executed=False,
                order_note=order_note,
                observe_mode=True,
            )
            report_path = write_performance_report(cfg)
            git_result = None
            if git_push and cfg.raw.get("git", {}).get("auto_push", True):
                git_result = _git_push_live(cfg, report_path)
            return {
                "status": "ok",
                "mode": "observe_only",
                "week_id": week_id,
                "signal": sig,
                "target": target,
                "account": {
                    "net_liquidation": snap.net_liquidation,
                    "total_cash": snap.total_cash,
                    "nav_return_since_start": (
                        pool_nav / capital_basis - 1.0 if capital_basis > 0 else 0.0
                    ),
                },
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
            observe_mode=False,
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


def run_live_unlock(
    cfg: IbkrLiveConfig,
    *,
    confirm: bool = False,
) -> dict[str, Any]:
    """Remove locked capital pool — does not move cash or cancel orders."""
    from .capital_pool import pool_state_path

    path = pool_state_path(cfg)
    if not path.exists():
        return {
            "status": "ok",
            "message": "No capital pool file — nothing to unlock.",
        }
    preview = json.loads(path.read_text()) if path.exists() else {}
    if not confirm:
        return {
            "status": "awaiting_confirmation",
            "message": "Re-run with --confirm to delete the locked pool record (no trades).",
            "preview": preview,
        }
    path.unlink()
    return {
        "status": "unlocked",
        "message": "Capital pool record removed. Cash was not moved. Use live-weekly --skip-trade to observe.",
        "removed": preview,
    }


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
            "observe_only": pool is None,
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
