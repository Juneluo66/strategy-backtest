#!/usr/bin/env python3
"""Run / advance PAPER_V1 forward day(s).

Signal at close; fills at next open. Append-only logs.
Does not modify strategy parameters.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backtest import effective_common_start
from config import ProjectConfig
from data_loader import fetch_prices, load_panels
from execution import ExecutionMode
from exposure import target_weight_for_beta
from indicators import build_indicator_panels, indicators_ready
from original_strategy import load_thresholds, select_target, state_from_row
from paper_trading import (
    PaperState,
    append_signal_row,
    build_signal_row,
    compute_paper_hashes,
    load_paper_config,
    mark_nav,
    paper_selector,
    rebalance_to_weights,
    rolling_metrics,
)
from robust_core import ROBUST_CORE_V1_THRESHOLDS, make_selector


def _load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def _verify_hash(cfg: dict) -> None:
    store = ROOT / "reports" / "runs" / "paper_v1" / "hashes.json"
    if not store.exists():
        raise SystemExit("Run scripts/init_paper_v1.py first")
    prev = json.loads(store.read_text(encoding="utf-8"))
    now = compute_paper_hashes(ROOT)
    if prev.get("composite_sha256") != now["composite_sha256"]:
        raise SystemExit(
            "PAPER_V1 composite hash mismatch — code/config changed. "
            "Create PAPER_V2; do not continue PAPER_V1 silently."
        )


def _append_metrics(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df_new = pd.DataFrame([row])
    if path.exists():
        old = pd.read_csv(path)
        if not old.empty and str(row["date"]) in set(old["date"].astype(str)):
            raise ValueError(f"metrics already logged for {row['date']}")
        df = pd.concat([old, df_new], ignore_index=True)
    else:
        df = df_new
    df.to_csv(path, index=False)


def _bh_nav(closes: pd.Series, start_nav: float, dates: pd.DatetimeIndex) -> pd.Series:
    px = closes.reindex(dates).ffill()
    rets = px.pct_change().fillna(0.0)
    return start_nav * (1 + rets).cumprod()


def run_forward(
    *,
    as_of: Optional[str] = None,
    catch_up: bool = True,
) -> int:
    paper_cfg = load_paper_config(ROOT)
    _verify_hash(paper_cfg)
    frozen = pd.Timestamp(paper_cfg["frozen_date"])

    proj = ProjectConfig.load(ROOT)
    universe = list(paper_cfg["universe"])
    fetch_prices(proj, symbols=universe, start="2010-01-01", refresh=False)
    opens, closes, _ = load_panels(proj, universe)

    params = paper_cfg["parameters"]
    indicators = build_indicator_panels(
        closes,
        rsi_period=int(params["rsi_period"]),
        spy_sma_period=int(params["spy_sma_period"]),
        qqq_sma_period=int(params["qqq_sma_period"]),
        tqqq_sma_period=int(params["tqqq_sma_period"]),
        universe=universe,
    )
    selector = paper_selector(paper_cfg)
    thresh = dict(paper_cfg["thresholds"])
    warmup = int(paper_cfg["backtest_reference"]["warmup_bars"])
    total_bps = float(paper_cfg["costs_base"]["total_bps"])

    cal = closes.index.intersection(opens.index).sort_values()
    eff = effective_common_start(closes, universe, warmup)
    trade_cal = cal[(cal >= max(frozen, eff))]
    if as_of:
        trade_cal = trade_cal[trade_cal <= pd.Timestamp(as_of)]
    if trade_cal.empty:
        print("No forward trading days yet (frozen_date in future or no data).")
        return 0

    state_path = ROOT / "logs" / "paper_state" / "account.json"
    pending_path = ROOT / "logs" / "paper_state" / "pending_order.json"
    signal_log = ROOT / "logs" / "paper_signals.csv"
    metrics_path = ROOT / "logs" / "paper_daily_metrics.csv"
    shadows_path = ROOT / "logs" / "paper_shadows.csv"
    nav_hist_path = ROOT / "logs" / "paper_state" / "nav_history.csv"

    acct = _load_json(
        state_path,
        {
            "cash": float(paper_cfg["paper_account"]["initial_cash"]),
            "shares": {},
            "weights": {"CASH": 1.0},
            "raw_target": None,
            "nav": float(paper_cfg["paper_account"]["initial_cash"]),
            "peak_nav": float(paper_cfg["paper_account"]["initial_cash"]),
            "days_in_position": 0,
            "last_signal_date": None,
            "last_fill_date": None,
        },
    )
    pending = _load_json(pending_path, None)

    # Determine which dates already logged
    logged = set()
    if signal_log.exists():
        sl = pd.read_csv(signal_log)
        if not sl.empty:
            logged = set(sl["date"].astype(str))

    init_nav = float(paper_cfg["paper_account"]["initial_cash"])
    # Shadow A: ORIGINAL full weight next-open (tracked via synthetic close-to-close for simplicity on shadow)
    # For operational simplicity shadows mark at close using signal target full weight.
    # Official Paper V1 uses next-open fills below.

    processed = 0
    dates = list(trade_cal)
    for i, date in enumerate(dates):
        date_s = str(pd.Timestamp(date).date())
        # Fill pending from yesterday at today's open
        px_open = {t: float(opens.loc[date, t]) for t in universe if t in opens.columns}
        px_close = {t: float(closes.loc[date, t]) for t in universe if t in closes.columns}

        state = PaperState(
            cash=float(acct["cash"]),
            weights=dict(acct.get("weights") or {}),
            shares={k: float(v) for k, v in (acct.get("shares") or {}).items()},
            raw_target=acct.get("raw_target"),
            nav=float(acct["nav"]),
            peak_nav=float(acct["peak_nav"]),
        )

        turnover = 0.0
        if pending and pending.get("fill_date") == date_s:
            new_w = pending["weights"]
            state, cost, trades = rebalance_to_weights(state, px_open, new_w, total_bps=total_bps)
            turnover = sum(abs(t.get("shares", 0) * t.get("price", 0)) for t in trades) / max(state.nav, 1e-9)
            state.raw_target = pending.get("raw_target")
            acct["last_fill_date"] = date_s
            pending = None
            _save_json(pending_path, None)

        # Mark NAV at close for metrics
        nav_close = mark_nav(state, px_close)
        state.nav = nav_close
        state.peak_nav = max(state.peak_nav, nav_close)

        # Generate today's close signal (append-only if new)
        ready = indicators_ready(
            date,
            closes,
            indicators,
            universe,
            rsi_period=int(params["rsi_period"]),
            spy_sma_period=int(params["spy_sma_period"]),
            warmup_bars=warmup,
        )
        if not ready:
            continue

        st = state_from_row(date, closes, indicators["rsi"], indicators["sma"])
        decision = selector(st, thresh)
        prev_raw = acct.get("raw_target")

        if date_s not in logged:
            row = build_signal_row(date, closes, indicators, decision, prev_raw, paper_cfg)
            append_signal_row(signal_log, row)
            logged.add(date_s)
            processed += 1
        else:
            # Already logged — still update account/metrics only if metrics missing
            row = None

        pos = target_weight_for_beta(
            decision.target,
            target_underlying_beta=float(paper_cfg["exposure"]["target_underlying_beta"]),
            asset_beta=paper_cfg.get("asset_underlying_beta"),
            uvxy_max_weight=float(paper_cfg["exposure"]["uvxy_max_portfolio_weight"]),
            defensive=paper_cfg["exposure"]["defensive_sleeve"],
        )

        # Schedule next-open fill if target changed
        if prev_raw != decision.target:
            if i + 1 < len(dates):
                fill_date = str(pd.Timestamp(dates[i + 1]).date())
                pending = {
                    "signal_date": date_s,
                    "fill_date": fill_date,
                    "raw_target": decision.target,
                    "weights": pos["weights"],
                    "mode": ExecutionMode.NEXT_OPEN_CONSERVATIVE.value,
                }
                _save_json(pending_path, pending)
            acct["days_in_position"] = 0
        else:
            acct["days_in_position"] = int(acct.get("days_in_position") or 0) + 1

        acct["raw_target"] = decision.target
        acct["cash"] = state.cash
        acct["shares"] = state.shares
        acct["weights"] = pos["weights"] if prev_raw != decision.target else state.weights
        acct["nav"] = state.nav
        acct["peak_nav"] = state.peak_nav
        acct["last_signal_date"] = date_s

        # NAV history
        nav_hist = pd.DataFrame()
        if nav_hist_path.exists():
            nav_hist = pd.read_csv(nav_hist_path)
        if nav_hist.empty or date_s not in set(nav_hist.get("date", pd.Series(dtype=str)).astype(str)):
            nav_hist = pd.concat(
                [nav_hist, pd.DataFrame([{"date": date_s, "nav": state.nav}])],
                ignore_index=True,
            )
            nav_hist.to_csv(nav_hist_path, index=False)

        # Daily metrics (skip if already present)
        metrics_exist = False
        if metrics_path.exists():
            mdf = pd.read_csv(metrics_path)
            metrics_exist = (not mdf.empty) and date_s in set(mdf["date"].astype(str))

        if not metrics_exist and len(nav_hist) >= 1:
            nav_s = nav_hist.set_index("date")["nav"].astype(float)
            nav_s.index = pd.to_datetime(nav_s.index)
            prev_nav = float(nav_s.iloc[-2]) if len(nav_s) >= 2 else init_nav
            ret = state.nav / prev_nav - 1 if prev_nav > 0 else 0.0
            spy_s = closes["SPY"].reindex(nav_s.index).ffill()
            qqq_s = closes["QQQ"].reindex(nav_s.index).ffill()
            rm = rolling_metrics(nav_s, spy_s, qqq_s)
            _append_metrics(
                metrics_path,
                {
                    "date": date_s,
                    "nav": state.nav,
                    "return": ret,
                    "drawdown": rm.get("drawdown"),
                    "raw_target": decision.target,
                    "paper_target": pos["paper_target"],
                    "branch_id": decision.branch_id,
                    "days_in_position": acct["days_in_position"],
                    "turnover": turnover,
                    "vol_20d": rm.get("vol_20d"),
                    "vol_60d": rm.get("vol_60d"),
                    "sharpe_20d": rm.get("sharpe_20d"),
                    "sharpe_60d": rm.get("sharpe_60d"),
                    "beta_spy": rm.get("beta_spy"),
                    "beta_qqq": rm.get("beta_qqq"),
                    "cost_bps_case": total_bps,
                    "version": "PAPER_V1",
                },
            )

        # Shadows (close-to-close mark for tracking)
        shadow_exist = False
        if shadows_path.exists():
            sdf = pd.read_csv(shadows_path)
            shadow_exist = (not sdf.empty) and date_s in set(sdf["date"].astype(str))
        if not shadow_exist:
            # Maintain simple shadow NAVs in state
            sh_state = _load_json(ROOT / "logs" / "paper_state" / "shadows.json", {
                "A": init_nav, "B": init_nav, "C": init_nav, "D": init_nav, "E": init_nav,
                "A_tgt": None, "B_tgt": None,
            })
            # D TQQQ, E SPY
            if i > 0:
                prev = dates[i - 1]
                for key, ticker in (("D", "TQQQ"), ("E", "SPY")):
                    p0 = float(closes.loc[prev, ticker])
                    p1 = float(closes.loc[date, ticker])
                    if p0 > 0:
                        sh_state[key] *= p1 / p0
                # C = paper NAV
                sh_state["C"] = state.nav
                # A = ORIGINAL full weight on its target
                st_o = state_from_row(date, closes, indicators["rsi"], indicators["sma"])
                d_o = select_target(st_o, load_thresholds(proj))
                # B = robust core full weight
                d_b = make_selector(drop_spy_rsi=True)(st_o, ROBUST_CORE_V1_THRESHOLDS)
                for key, dec in (("A", d_o), ("B", d_b)):
                    tgt = dec.target
                    prev_t = sh_state.get(f"{key}_tgt")
                    if prev_t and prev_t in closes.columns:
                        p0 = float(closes.loc[prev, prev_t])
                        p1 = float(closes.loc[date, prev_t])
                        if p0 > 0 and np.isfinite(p1):
                            sh_state[key] *= p1 / p0
                    sh_state[f"{key}_tgt"] = tgt
            else:
                sh_state["C"] = state.nav
            _save_json(ROOT / "logs" / "paper_state" / "shadows.json", sh_state)
            row_s = {
                "date": date_s,
                "SHADOW_A_nav": sh_state["A"],
                "SHADOW_B_nav": sh_state["B"],
                "SHADOW_C_nav": sh_state["C"],
                "SHADOW_D_nav": sh_state["D"],
                "SHADOW_E_nav": sh_state["E"],
            }
            if shadows_path.exists():
                old = pd.read_csv(shadows_path)
                pd.concat([old, pd.DataFrame([row_s])], ignore_index=True).to_csv(shadows_path, index=False)
            else:
                pd.DataFrame([row_s]).to_csv(shadows_path, index=False)

        _save_json(state_path, acct)

        if not catch_up:
            break

    print(f"Forward pass done. New signal rows: {processed}. Last: {acct.get('last_signal_date')}")
    print(f"Paper NAV: {acct.get('nav'):.2f} raw_target={acct.get('raw_target')}")
    return 0


def main() -> int:
    as_of = None
    catch_up = True
    if len(sys.argv) > 1:
        as_of = sys.argv[1]
    if "--no-catch-up" in sys.argv:
        catch_up = False
    return run_forward(as_of=as_of, catch_up=catch_up)


if __name__ == "__main__":
    raise SystemExit(main())
