from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from .btc_signals import load_btc_weekly_signal
from .config import V2Config
from .data import load_adj_close
from .matrix import _eval_combo
from .metrics import summary_stats, vol_matched_weight
from .simulate import simulate_dynamic_off, simulate_fixed_pair, slice_period


def run_off_rules(config: V2Config) -> dict[str, Any]:
    splits = config.raw["splits"]
    train_start = pd.Timestamp(splits["train"]["start"])
    train_end = pd.Timestamp(splits["train"]["end"])
    test_start = pd.Timestamp(splits["test"]["start"])
    test_end = pd.Timestamp(splits["test"]["end"])

    on_sym = "QQQ"
    prices = load_adj_close(config, [on_sym, "SHY", "IEF"])
    etf_cal = prices[[on_sym, "SHY", "IEF"]].dropna().index
    risk_on_sig = load_btc_weekly_signal(config, etf_cal)

    on_px = prices[on_sym]
    shy_px = prices["SHY"]
    ief_px = prices["IEF"]

    # Baseline v1 OFF
    strat_shy, _ = simulate_fixed_pair(risk_on_sig, on_px, shy_px)
    rule_spec = config.raw["off_rules_v2"]["ietf_sma200_shy"]
    strat_dyn, pos_dyn = simulate_dynamic_off(
        risk_on_sig,
        on_px,
        ief_px,
        shy_px,
        trend_sma=int(rule_spec["sma_window"]),
        etf_cal=etf_cal,
    )

    def pack_period(strat: pd.Series, label: str, start: pd.Timestamp, end: pd.Timestamp) -> dict:
        s = slice_period(strat, start, end)
        on_r = slice_period(on_px.pct_change(fill_method=None), start, end).reindex(s.index).fillna(0.0)
        shy_r = slice_period(shy_px.pct_change(fill_method=None), start, end).reindex(s.index).fillna(0.0)
        w = vol_matched_weight(s, on_r, shy_r)
        static = w * on_r + (1 - w) * shy_r
        st = summary_stats(s)
        active = float((1 + (s - static)).prod() - 1.0)
        return {
            "label": label,
            "stats": st,
            "cum_active_vs_vol_matched_qqq_shy": active,
            "max_dd": st.get("max_dd"),
        }

    train_shy = pack_period(strat_shy, "QQQ/SHY_fixed", train_start, train_end)
    train_dyn = pack_period(strat_dyn, "QQQ/IEFtrend_SHY", train_start, train_end)

    # Test with train-calibrated vol match
    s_train_shy = slice_period(strat_shy, train_start, train_end)
    on_tr = slice_period(on_px.pct_change(fill_method=None), train_start, train_end)
    shy_tr = slice_period(shy_px.pct_change(fill_method=None), train_start, train_end)
    on_tr = on_tr.reindex(s_train_shy.index).fillna(0.0)
    shy_tr = shy_tr.reindex(s_train_shy.index).fillna(0.0)
    w_train = vol_matched_weight(s_train_shy, on_tr, shy_tr)

    test_shy_row = _eval_combo(
        on_sym, "SHY", prices, risk_on_sig, test_start, test_end,
        calibrate_vol_on=s_train_shy, calibrate_on_r=on_tr, calibrate_off_r=shy_tr,
    )
    # Dynamic OFF test — manual
    s_test_dyn = slice_period(strat_dyn, test_start, test_end)
    on_te = slice_period(on_px.pct_change(fill_method=None), test_start, test_end).reindex(s_test_dyn.index).fillna(0.0)
    shy_te = slice_period(shy_px.pct_change(fill_method=None), test_start, test_end).reindex(s_test_dyn.index).fillna(0.0)
    static_te = w_train * on_te + (1 - w_train) * shy_te
    st_dyn = summary_stats(s_test_dyn)
    active_dyn = float((1 + (s_test_dyn - static_te)).prod() - 1.0)

    train_winner = "IEF_trend_rule" if train_dyn["stats"].get("sharpe", 0) > train_shy["stats"].get("sharpe", 0) else "SHY_fixed"
    test_dyn_pass = st_dyn.get("sharpe", 0) > 1.0 and active_dyn > 0
    test_shy_pass = test_shy_row.get("cum_active", 0) > 0 and test_shy_row.get("strategy", {}).get("sharpe", 0) > 1.0

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "rule": rule_spec,
        "train": {"shy_fixed": train_shy, "ief_trend": train_dyn, "train_winner_sharpe": train_winner},
        "test_locked": {
            "shy_fixed": {
                "stats": test_shy_row.get("strategy"),
                "cum_active": test_shy_row.get("cum_active"),
                "pass": test_shy_pass,
            },
            "ief_trend": {
                "stats": st_dyn,
                "cum_active": active_dyn,
                "pass": test_dyn_pass,
            },
        },
        "off_sleeve_ief_pct": float((pos_dyn.reindex(s_test_dyn.index) == "OFF_TREND").mean()) if len(s_test_dyn) else np.nan,
        "judgment": _off_judgment(train_winner, test_dyn_pass, test_shy_pass),
    }


def _off_judgment(train_winner: str, dyn_pass: bool, shy_pass: bool) -> str:
    if train_winner == "IEF_trend_rule" and dyn_pass:
        return "IEF_TREND_RULE_TRAIN_WIN_AND_TEST_PASS"
    if train_winner == "IEF_trend_rule" and not dyn_pass:
        return "IEF_TREND_RULE_TRAIN_WIN_TEST_FAIL_DO_NOT_ADOPT"
    if shy_pass and not dyn_pass:
        return "SHY_REMAINS_BETTER_OFF_SLEEVE"
    return "OFF_RULE_MIXED"


def render_off_rules_md(p: dict) -> str:
    lines = [
        "# OFF Sleeve Tiny Rule (QQQ risk-on frozen)",
        "",
        f"Rule: `{p['rule']['description']}`",
        f"Judgment: **`{p['judgment']}`**",
        "",
        "## Train (selection allowed)",
        "",
        f"| Variant | Sharpe | MaxDD | Cum active |",
        f"|---|---:|---:|---:|",
        f"| SHY fixed | {p['train']['shy_fixed']['stats'].get('sharpe', 0):.3f} | "
        f"{100*p['train']['shy_fixed']['max_dd']:.1f}% | "
        f"{100*p['train']['shy_fixed']['cum_active_vs_vol_matched_qqq_shy']:.1f}% |",
        f"| IEF trend rule | {p['train']['ief_trend']['stats'].get('sharpe', 0):.3f} | "
        f"{100*p['train']['ief_trend']['max_dd']:.1f}% | "
        f"{100*p['train']['ief_trend']['cum_active_vs_vol_matched_qqq_shy']:.1f}% |",
        "",
        f"Train Sharpe winner: **{p['train']['train_winner_sharpe']}**",
        "",
        "## Test (locked — no re-selection)",
        "",
    ]
    ts = p["test_locked"]["shy_fixed"]["stats"] or {}
    td = p["test_locked"]["ief_trend"]["stats"] or {}
    lines += [
        f"| Variant | Sharpe | MaxDD | Cum active | Pass |",
        f"|---|---:|---:|---:|---|",
        f"| SHY fixed | {ts.get('sharpe', 0):.3f} | {100*ts.get('max_dd', 0):.1f}% | "
        f"{100*p['test_locked']['shy_fixed']['cum_active']:.1f}% | "
        f"{'✓' if p['test_locked']['shy_fixed']['pass'] else '✗'} |",
        f"| IEF trend rule | {td.get('sharpe', 0):.3f} | {100*td.get('max_dd', 0):.1f}% | "
        f"{100*p['test_locked']['ief_trend']['cum_active']:.1f}% | "
        f"{'✓' if p['test_locked']['ief_trend']['pass'] else '✗'} |",
        "",
    ]
    return "\n".join(lines)


def write_off_rules_report(config: V2Config, payload: dict) -> None:
    import shutil

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.reports_dir / "runs" / f"{stamp}_off_rules"
    run_dir.mkdir(parents=True, exist_ok=True)
    md = render_off_rules_md(payload)
    (run_dir / "off_rules_payload.json").write_text(json.dumps(payload, indent=2, default=str))
    (run_dir / "off_rules.md").write_text(md)
    latest = config.reports_dir / "off_rules.md"
    shutil.copy2(run_dir / "off_rules.md", latest)
