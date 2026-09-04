"""Isolated strategy capital pool — locked cash, no silent deposits."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .ibkr_config import IbkrLiveConfig


@dataclass
class CapitalPoolState:
    initial_capital: float
    injected_capital: float
    account_id: str
    set_utc: str
    locked: bool
    basis: str  # "cash"
    qqq_shares: float
    shy_shares: float
    strategy_cash: float
    injections: list[dict[str, Any]]
    note: str = ""
    qqq_cost_basis_per_share: float = 0.0
    shy_cost_basis_per_share: float = 0.0
    fees_paid_total: float = 0.0

    @property
    def total_capital_basis(self) -> float:
        return self.initial_capital + self.injected_capital

    def book_cost_nav(self) -> float:
        """NAV at cost (fees included in per-share basis)."""
        nav = self.strategy_cash
        if self.qqq_shares and self.qqq_cost_basis_per_share:
            nav += self.qqq_shares * self.qqq_cost_basis_per_share
        elif self.qqq_shares:
            nav += self.qqq_shares  # fallback
        if self.shy_shares and self.shy_cost_basis_per_share:
            nav += self.shy_shares * self.shy_cost_basis_per_share
        elif self.shy_shares:
            nav += self.shy_shares
        return nav

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_capital": self.initial_capital,
            "injected_capital": self.injected_capital,
            "total_capital_basis": self.total_capital_basis,
            "account_id": self.account_id,
            "set_utc": self.set_utc,
            "locked": self.locked,
            "basis": self.basis,
            "qqq_shares": self.qqq_shares,
            "shy_shares": self.shy_shares,
            "strategy_cash": self.strategy_cash,
            "qqq_cost_basis_per_share": self.qqq_cost_basis_per_share,
            "shy_cost_basis_per_share": self.shy_cost_basis_per_share,
            "fees_paid_total": self.fees_paid_total,
            "injections": self.injections,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapitalPoolState:
        initial = float(data["initial_capital"])
        injected = float(data.get("injected_capital", 0.0))
        return cls(
            initial_capital=initial,
            injected_capital=injected,
            account_id=str(data.get("account_id", "")),
            set_utc=str(data.get("set_utc", "")),
            locked=bool(data.get("locked", True)),
            basis=str(data.get("basis", "cash")),
            qqq_shares=float(data.get("qqq_shares", 0.0)),
            shy_shares=float(data.get("shy_shares", 0.0)),
            strategy_cash=float(data.get("strategy_cash", initial + injected)),
            qqq_cost_basis_per_share=float(data.get("qqq_cost_basis_per_share", 0.0)),
            shy_cost_basis_per_share=float(data.get("shy_cost_basis_per_share", 0.0)),
            fees_paid_total=float(data.get("fees_paid_total", 0.0)),
            injections=list(data.get("injections", [])),
            note=str(data.get("note", "")),
        )


def pool_state_path(cfg: IbkrLiveConfig) -> Path:
    rel = cfg.raw.get("capital_pool", {}).get(
        "state_path", "reports/live/capital_pool.json"
    )
    return cfg.project_root / rel


def load_pool_state(cfg: IbkrLiveConfig) -> Optional[CapitalPoolState]:
    path = pool_state_path(cfg)
    if not path.exists():
        return None
    return CapitalPoolState.from_dict(json.loads(path.read_text()))


def save_pool_state(cfg: IbkrLiveConfig, state: CapitalPoolState) -> Path:
    path = pool_state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2))
    return path


def init_pool_from_cash(
    cfg: IbkrLiveConfig,
    *,
    cash_amount: float,
    account_id: str,
    note: str = "locked_cash_baseline",
    overwrite: bool = False,
) -> CapitalPoolState:
    """Lock account cash as the strategy's isolated capital envelope."""
    existing = load_pool_state(cfg)
    if existing is not None and existing.locked and not overwrite:
        raise RuntimeError(
            "Capital pool already locked. Use live-inject-capital to add funds, "
            "or live-init --force to re-baseline (destructive)."
        )
    if cash_amount <= 0:
        raise ValueError("cash_amount must be positive")

    state = CapitalPoolState(
        initial_capital=cash_amount,
        injected_capital=0.0,
        account_id=account_id,
        set_utc=datetime.now(timezone.utc).isoformat(),
        locked=True,
        basis="cash",
        qqq_shares=0.0,
        shy_shares=0.0,
        strategy_cash=cash_amount,
        injections=[],
        note=note,
    )
    save_pool_state(cfg, state)
    return state


def inject_capital(
    cfg: IbkrLiveConfig,
    amount: float,
    *,
    note: str = "manual_injection",
) -> CapitalPoolState:
    """Explicit capital add — only path to grow the pool beyond P&L."""
    state = load_pool_state(cfg)
    if state is None or not state.locked:
        raise RuntimeError("No locked capital pool. Run live-init first.")
    if amount <= 0:
        raise ValueError("injection amount must be positive")

    state.injected_capital += amount
    state.strategy_cash += amount
    state.injections.append(
        {
            "amount": amount,
            "utc": datetime.now(timezone.utc).isoformat(),
            "note": note,
        }
    )
    save_pool_state(cfg, state)
    return state


def compute_pool_nav(
    state: CapitalPoolState,
    *,
    qqq_price: float,
    shy_price: float,
) -> float:
    """Mark-to-market NAV of the isolated strategy sleeve only."""
    nav = state.strategy_cash
    if state.qqq_shares:
        nav += state.qqq_shares * qqq_price
    if state.shy_shares:
        nav += state.shy_shares * shy_price
    return nav


def update_pool_positions(
    state: CapitalPoolState,
    *,
    qqq_shares: float,
    shy_shares: float,
    strategy_cash: float,
) -> CapitalPoolState:
    state.qqq_shares = qqq_shares
    state.shy_shares = shy_shares
    state.strategy_cash = strategy_cash
    return state
