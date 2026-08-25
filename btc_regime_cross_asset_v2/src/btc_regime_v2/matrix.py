"""30-combo matrix: risk-on × risk-off with vol-matched benchmarks."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from .btc_signals import load_btc_weekly_signal
from .config import V2Config
from .data import load_adj_close
from .metrics import summary_stats, vol_matched_weight
from .simulate import simulate_fixed_pair, slice_period


def _eval_combo(
    on_sym: str,
    off_sym: str,
    prices: pd.DataFrame,
    risk_on_sig: pd.Series,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    calibrate_vol_on: pd.Series | None = None,
    calibrate_on_r: pd.Series | None = None,
    calibrate_off_r: pd.Series | None = None,
) -> dict[str, Any]:
    on_px = prices[on_sym]
    off_px = prices[off_sym]
    strat, pos = simulate_fixed_pair(risk_on_sig, on_px, off_px)
    s = slice_period(strat, start, end)
    if len(s) < 5:
        return {"on": on_sym, "off": off_sym, "error": "insufficient_data"}

    on_r = slice_period(on_px.pct_change(fill_method=None), start, end)
    off_r = slice_period(off_px.pct_change(fill_method=None), start, end)
    on_r = on_r.reindex(s.index).fillna(0.0)
    off_r = off_r.reindex(s.index).fillna(0.0)

    if calibrate_vol_on is not None and calibrate_on_r is not None and calibrate_off_r is not None:
        w = vol_matched_weight(calibrate_vol_on, calibrate_on_r, calibrate_off_r)
    else:
        w = vol_matched_weight(s, on_r, off_r)

    static = w * on_r + (1 - w) * off_r
    st = summary_stats(s)
    bh = summary_stats(on_r)
    st_static = summary_stats(static)
    active = s - static

    return {
        "on": on_sym,
        "off": off_sym,
        "label": f"{on_sym}/{off_sym}",
        "strategy": st,
        "buyhold_on": bh,
        "vol_matched_static": st_static,
        "vol_matched_w_on": w,
        "pct_on": float((pos.reindex(s.index) == "ON").mean()),
        "edge_vs_vol_matched": {
            "cagr_pp": 100 * (st.get("cagr", np.nan) - st_static.get("cagr", np.nan)),
            "sharpe_diff": st.get("sharpe", np.nan) - st_static.get("sharpe", np.nan),
            "maxdd_pp": 100 * (st.get("max_dd", np.nan) - st_static.get("max_dd", np.nan)),
        },
        "cum_active": float((1 + active).prod() - 1.0),
    }


def run_matrix(
    config: V2Config,
    *,
    period: str = "all",
) -> dict[str, Any]:
    matrix = config.raw["matrix"]
    splits = config.raw["splits"]
    if period == "train":
        start = pd.Timestamp(splits["train"]["start"])
        end = pd.Timestamp(splits["train"]["end"])
    elif period == "test":
        start = pd.Timestamp(splits["test"]["start"])
        end = pd.Timestamp(splits["test"]["end"])
    else:
        start = pd.Timestamp(config.raw["data"]["effective_start"])
        end = pd.Timestamp(splits["test"]["end"])

    prices = load_adj_close(config, matrix["risk_on"] + matrix["risk_off"])
    etf_cal = prices.dropna(how="any").index
    risk_on_sig = load_btc_weekly_signal(config, etf_cal)

    rows = []
    for on_sym in matrix["risk_on"]:
        for off_sym in matrix["risk_off"]:
            row = _eval_combo(on_sym, off_sym, prices, risk_on_sig, start, end)
            rows.append(row)

    # Train-calibrated vol match for test period
    if period == "test":
        train_start = pd.Timestamp(splits["train"]["start"])
        train_end = pd.Timestamp(splits["train"]["end"])
        rows_cal = []
        for on_sym in matrix["risk_on"]:
            for off_sym in matrix["risk_off"]:
                on_px = prices[on_sym]
                off_px = prices[off_sym]
                strat, _ = simulate_fixed_pair(risk_on_sig, on_px, off_px)
                s_train = slice_period(strat, train_start, train_end)
                on_tr = slice_period(on_px.pct_change(fill_method=None), train_start, train_end)
                off_tr = slice_period(off_px.pct_change(fill_method=None), train_start, train_end)
                on_tr = on_tr.reindex(s_train.index).fillna(0.0)
                off_tr = off_tr.reindex(s_train.index).fillna(0.0)
                row = _eval_combo(
                    on_sym,
                    off_sym,
                    prices,
                    risk_on_sig,
                    start,
                    end,
                    calibrate_vol_on=s_train,
                    calibrate_on_r=on_tr,
                    calibrate_off_r=off_tr,
                )
                row["vol_match_calibrated_on"] = "train"
                rows_cal.append(row)
        rows = rows_cal

    ranked = sorted(
        [r for r in rows if "strategy" in r],
        key=lambda x: x["strategy"].get("sharpe", -999),
        reverse=True,
    )

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "period": period,
        "sample": {"start": str(start.date()), "end": str(end.date())},
        "btc_gate": config.raw["btc_gate"],
        "n_combos": len(rows),
        "combos": rows,
        "top5_sharpe": [r["label"] for r in ranked[:5]],
        "reference_v1": f"{matrix['risk_on'][0]}/SHY",
    }


def render_matrix_md(payload: dict) -> str:
    lines = [
        f"# Matrix Scan — {payload['period']}",
        "",
        f"Sample: `{payload['sample']['start']}` → `{payload['sample']['end']}`",
        f"BTC gate: SMA{payload['btc_gate']['sma_window']} + MOM{payload['btc_gate']['momentum_window']} (frozen)",
        "",
        "| ON/OFF | CAGR | Sharpe | Vol | MaxDD | w_on static | Edge Sharpe | Edge CAGR pp | Cum active |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in payload["combos"]:
        if "strategy" not in r:
            continue
        st = r["strategy"]
        e = r["edge_vs_vol_matched"]
        lines.append(
            f"| {r['label']} | {100*st['cagr']:.2f}% | {st['sharpe']:.3f} | "
            f"{100*st['ann_vol']:.2f}% | {100*st['max_dd']:.2f}% | {r['vol_matched_w_on']:.2f} | "
            f"{e['sharpe_diff']:.3f} | {e['cagr_pp']:.2f} | {100*r['cum_active']:.1f}% |"
        )
    lines += [
        "",
        f"Top 5 Sharpe: {', '.join(payload['top5_sharpe'])}",
        "",
        "v1 reference: `QQQ/SHY` — compare rows before declaring a v2 winner.",
        "",
    ]
    return "\n".join(lines)


def write_matrix_report(config: V2Config, payload: dict) -> None:
    import shutil

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.reports_dir / "runs" / f"{stamp}_matrix_{payload['period']}"
    run_dir.mkdir(parents=True, exist_ok=True)
    md = render_matrix_md(payload)
    (run_dir / "matrix_payload.json").write_text(json.dumps(payload, indent=2, default=str))
    (run_dir / "matrix.md").write_text(md)
    latest = config.reports_dir / f"matrix_{payload['period']}.md"
    shutil.copy2(run_dir / "matrix.md", latest)
