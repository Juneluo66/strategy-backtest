"""Run parallel paper books under IBKR-like constraints."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .config import DualMomentumConfig
from .paper_trading import (
    PaperConfig,
    PortfolioState,
    execute_rebalance,
    load_paper_config,
    mark_to_market,
    simulate_spy_only_paper,
    simulate_two_asset_paper,
    write_paper_logs,
)
from .signals import month_end_index, next_trading_day


def _execution_dates(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    out = []
    for sig in month_end_index(index):
        exe = next_trading_day(index, sig)
        if exe is not None:
            out.append(pd.Timestamp(exe))
    return out


def _dc_weight_map(targets: pd.DataFrame) -> dict[pd.Timestamp, dict[str, float]]:
    """Map execution_date -> {symbol: weight} for D+C."""
    if targets.empty:
        return {}
    t = targets.copy()
    t["execution_date"] = pd.to_datetime(t["execution_date"])
    out: dict[pd.Timestamp, dict[str, float]] = {}
    for exe, g in t.groupby("execution_date"):
        out[pd.Timestamp(exe)] = {str(r["symbol"]): float(r["weight"]) for _, r in g.iterrows()}
    return out


def simulate_spy_dc_lookthrough_paper(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    dc_targets: pd.DataFrame,
    *,
    w_spy: float,
    w_dc: float,
    cfg: PaperConfig,
    portfolio_id: str,
) -> dict[str, Any]:
    """
    Trade look-through holdings:
      weight(sym) = w_spy * 1_{SPY} + w_dc * weight_dc(sym)
    Rebalance on D+C execution dates (month-end signal → next open).
    """
    idx = opens.index.intersection(closes.index).sort_values()
    dc_map = _dc_weight_map(dc_targets)
    if not dc_map:
        raise ValueError("D+C targets empty; cannot run look-through paper book")
    start = min(dc_map.keys())
    idx = idx[idx >= start]
    exec_dates = set(d for d in _execution_dates(idx) if d >= start) | set(dc_map.keys())
    state = PortfolioState(cash=cfg.initial_cash)
    logs: list[dict[str, Any]] = []
    rows = []
    prev_nav = None
    last_dc_w = dc_map[start]

    for date in idx:
        if date in dc_map:
            last_dc_w = dc_map[date]
        if date in exec_dates or prev_nav is None:
            lt: dict[str, float] = {"SPY": w_spy}
            for sym, w in last_dc_w.items():
                lt[sym] = lt.get(sym, 0.0) + w_dc * float(w)
            s = sum(lt.values())
            if s > 0:
                lt = {k: v / s for k, v in lt.items()}
            prices = {}
            for sym in list(lt.keys()) + list(state.shares.keys()):
                if sym in opens.columns and pd.notna(opens.loc[date, sym]):
                    prices[sym] = float(opens.loc[date, sym])
            state, day_logs, _ = execute_rebalance(
                state,
                target_weights=lt,
                prices=prices,
                cfg=cfg,
                asof=date,
                portfolio_id=portfolio_id,
            )
            for entry in day_logs:
                entry["lookthrough_targets"] = lt
            logs.extend(day_logs)

        close_prices = {
            sym: float(closes.loc[date, sym])
            for sym in state.shares
            if sym in closes.columns and pd.notna(closes.loc[date, sym])
        }
        nav = mark_to_market(state, close_prices)
        ret = 0.0 if prev_nav is None or prev_nav <= 0 else nav / prev_nav - 1
        rows.append({"date": date, "net_return": ret, "nav": nav, "cash": state.cash})
        prev_nav = nav

    eq = pd.DataFrame(rows).set_index("date")
    eq["equity_net"] = eq["nav"] / eq["nav"].iloc[0] if len(eq) and eq["nav"].iloc[0] > 0 else 1.0
    return {"equity": eq, "logs": logs, "final_state": asdict(state), "portfolio_id": portfolio_id}


def run_paper_books(
    config: DualMomentumConfig,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    dc_targets: pd.DataFrame,
    directory: Path,
) -> dict[str, Any]:
    paper_path = config.project_root / "configs" / "paper_trading.yaml"
    raw = yaml.safe_load(paper_path.read_text(encoding="utf-8"))
    cfg = load_paper_config(paper_path)
    books = raw.get("books", [])
    exec_dates = _execution_dates(opens.index.intersection(closes.index))
    results = {}

    for book in books:
        bid = book["id"]
        btype = book["type"]
        if btype == "spy_only":
            run = simulate_spy_only_paper(opens, closes, cfg, portfolio_id=bid)
        elif btype == "two_asset":
            run = simulate_two_asset_paper(
                opens,
                closes,
                targets={k: float(v) for k, v in book["weights"].items()},
                rebalance_execution_dates=exec_dates,
                cfg=cfg,
                portfolio_id=bid,
            )
        elif btype == "spy_dc_lookthrough":
            run = simulate_spy_dc_lookthrough_paper(
                opens,
                closes,
                dc_targets,
                w_spy=float(book["spy"]),
                w_dc=float(book["dc"]),
                cfg=cfg,
                portfolio_id=bid,
            )
        else:
            raise ValueError(btype)
        write_paper_logs(directory, run)
        results[bid] = {
            "role": book.get("role"),
            "type": btype,
            "final_nav": float(run["equity"]["nav"].iloc[-1]) if len(run["equity"]) else None,
            "n_log_events": len(run["logs"]),
            "final_state": run["final_state"],
        }
    summary = {
        "paper_config": raw,
        "books": results,
        "execution_dates": [str(d.date()) for d in exec_dates[:5]] + ["..."],
        "n_execution_dates": len(exec_dates),
    }
    (directory / "paper_books_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary
