"""Risk-matched benchmarks: static mix and vol/beta-matched QQQ/SHY."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import ProjectConfig
from .data import load_adj_close
from .metrics import summary_stats
from .reconciliation import (
    fetch_bitfinex_btc,
    load_ohlc_symbol,
    qc_weekly_signals,
    simulate_from_weekly_signal,
    week_start_equity_dates,
)


def _sharpe(r: pd.Series) -> float:
    x = r.dropna()
    if len(x) < 5 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / x.std(ddof=1) * np.sqrt(252))


def _ann_vol(r: pd.Series) -> float:
    x = r.dropna()
    return float(x.std(ddof=1) * np.sqrt(252)) if len(x) > 5 else float("nan")


def run_risk_matched(config: ProjectConfig) -> dict[str, Any]:
    prices = load_adj_close(config)
    bf = fetch_bitfinex_btc(config)
    qqq_ohlc = load_ohlc_symbol(config, "QQQ")
    shy_ohlc = load_ohlc_symbol(config, "SHY")
    qqq = prices["QQQ"]
    shy = prices["SHY"]
    spy = prices["SPY"]
    etf_cal = prices[["QQQ", "SHY", "SPY"]].dropna().index
    week_starts = week_start_equity_dates(etf_cal)

    sigs = qc_weekly_signals(bf["Close"].astype(float), week_starts)
    valid = sigs.dropna(subset=["risk_on"])
    valid = valid[valid["week_start"] >= pd.Timestamp("2014-11-05")]
    signal = valid.set_index("week_start")["risk_on"].astype("boolean")

    # Strategy: QC week-start, close path adj, 5bps one-way + spreads ≈ 13 RT
    cost_rt = 2 * float(config.raw["rules"].get("costs_bps_one_way", 5)) + 1.0 + 2.0
    strat, pos = simulate_from_weekly_signal(
        signal,
        qqq,
        shy,
        fill="open",
        cost_bps_rt=cost_rt,
        use_adj=False,
        qqq_close=qqq_ohlc["Close"].astype(float),
        shy_close=shy_ohlc["Close"].astype(float),
        qqq_open=qqq_ohlc["Open"].astype(float),
        shy_open=shy_ohlc["Open"].astype(float),
    )
    # Also adj 0bps for discovery comparison
    strat0, pos0 = simulate_from_weekly_signal(
        signal, qqq, shy, fill="close", cost_bps_rt=0.0, use_adj=True
    )

    t0 = pd.Timestamp(valid["week_start"].iloc[0])
    t1 = etf_cal.max()
    s = strat0.loc[t0:t1].dropna().iloc[1:]
    q = qqq.pct_change().reindex(s.index).fillna(0.0)
    h = shy.pct_change().reindex(s.index).fillna(0.0)

    # Occupancy from positions
    occ_qqq = float((pos0.reindex(s.index) == "QQQ").mean())
    w = occ_qqq
    static = w * q + (1 - w) * h

    # Vol-matched: find w_vol in [0,1] s.t. ann_vol(w*Q+(1-w)*H) ≈ ann_vol(strategy)
    target_vol = _ann_vol(s)
    grid = np.linspace(0, 1, 101)
    vols = np.array([_ann_vol(ww * q + (1 - ww) * h) for ww in grid])
    w_vol = float(grid[int(np.argmin(np.abs(vols - target_vol)))])
    vol_matched = w_vol * q + (1 - w_vol) * h

    # Beta-matched vs SPY: strategy beta, match static mix beta
    spy_r = spy.pct_change().reindex(s.index).fillna(0.0)

    def _beta(y, x):
        a = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
        if len(a) < 50 or a["x"].std() == 0:
            return float("nan")
        return float(np.cov(a["y"], a["x"], ddof=1)[0, 1] / a["x"].var(ddof=1))

    b_strat = _beta(s, spy_r)
    betas = np.array([_beta(ww * q + (1 - ww) * h, spy_r) for ww in grid])
    w_beta = float(grid[int(np.nanargmin(np.abs(betas - b_strat)))])
    beta_matched = w_beta * q + (1 - w_beta) * h

    def pack(r: pd.Series, label: str) -> dict:
        st = summary_stats(r)
        return {
            "label": label,
            "cagr": st.get("cagr"),
            "sharpe": _sharpe(r),
            "ann_vol": st.get("ann_vol"),
            "max_dd": st.get("max_drawdown"),
            "final_nav": st.get("final_nav"),
        }

    rows = [
        pack(s, "BTC_timing_adj_0bps"),
        pack(q, "100pct_QQQ"),
        pack(h, "100pct_SHY"),
        pack(static, f"static_{w:.2f}_QQQ_{1-w:.2f}_SHY"),
        pack(vol_matched, f"vol_matched_wQQQ={w_vol:.2f}"),
        pack(beta_matched, f"beta_matched_wQQQ={w_beta:.2f}"),
    ]
    # With costs on strategy
    sc = strat.loc[t0:t1].dropna().iloc[1:]
    rows.insert(1, pack(sc, f"BTC_timing_close_open_costRT_{cost_rt:.0f}bps"))

    # Edge vs risk-matched
    def edge(a: dict, b: dict) -> dict:
        return {
            "cagr_pp": 100 * (float(a["cagr"]) - float(b["cagr"])) if a["cagr"] == a["cagr"] else np.nan,
            "sharpe_diff": float(a["sharpe"]) - float(b["sharpe"]),
            "maxdd_pp": 100 * (float(a["max_dd"]) - float(b["max_dd"])),
        }

    timing = rows[0]
    judgment = "TIMING_BEATS_RISK_MATCHED_STATIC"
    e_vol = edge(timing, rows[-2])
    e_occ = edge(timing, rows[3] if "static_" in rows[3]["label"] else rows[4])
    # find static row
    static_row = next(r for r in rows if r["label"].startswith("static_"))
    vol_row = next(r for r in rows if r["label"].startswith("vol_matched"))
    e_vol = edge(timing, vol_row)
    e_occ = edge(timing, static_row)
    if e_vol["sharpe_diff"] < 0.05 and abs(e_vol["cagr_pp"]) < 1.0:
        judgment = "TIMING_LITTLE_BETTER_THAN_VOL_MATCHED_STATIC"
    elif e_vol["sharpe_diff"] < 0:
        judgment = "VOL_MATCHED_STATIC_COMPETITIVE_OR_BETTER"

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "sample": {"t0": str(t0.date()), "t1": str(pd.Timestamp(t1).date())},
        "occupancy_qqq": w,
        "vol_matched_w_qqq": w_vol,
        "beta_matched_w_qqq": w_beta,
        "strategy_beta_vs_spy": b_strat,
        "target_vol": target_vol,
        "comparisons": rows,
        "edge_vs_occupancy_static": e_occ,
        "edge_vs_vol_matched": e_vol,
        "judgment": judgment,
    }


def render_risk_matched_md(payload: dict) -> str:
    lines = [
        "# Risk-Matched Benchmarks",
        "",
        f"## Judgment: `{payload['judgment']}`",
        "",
        f"Sample: `{payload['sample']['t0']}` → `{payload['sample']['t1']}`",
        f"- Strategy QQQ occupancy: `{100*payload['occupancy_qqq']:.1f}%`",
        f"- Vol-matched static w_QQQ: `{payload['vol_matched_w_qqq']:.2f}`",
        f"- Beta-matched static w_QQQ: `{payload['beta_matched_w_qqq']:.2f}` (β_strat=`{payload['strategy_beta_vs_spy']:.3f}`)",
        "",
        "| Portfolio | CAGR | Sharpe | Vol | MaxDD | Final NAV |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in payload["comparisons"]:
        lines.append(
            f"| {r['label']} | {100*r['cagr']:.2f}% | {r['sharpe']:.3f} | "
            f"{100*r['ann_vol']:.2f}% | {100*r['max_dd']:.2f}% | {r['final_nav']:.3f} |"
        )
    e = payload["edge_vs_vol_matched"]
    eo = payload["edge_vs_occupancy_static"]
    lines += [
        "",
        f"- vs occupancy static: ΔCAGR `{e.get('cagr_pp', eo['cagr_pp']):.2f}` pp wait",
        f"- vs occupancy static: ΔCAGR `{eo['cagr_pp']:.2f}` pp, ΔSharpe `{eo['sharpe_diff']:.3f}`",
        f"- vs vol-matched static: ΔCAGR `{e['cagr_pp']:.2f}` pp, ΔSharpe `{e['sharpe_diff']:.3f}`",
        "",
        "100% QQQ is not a fair risk peer when the strategy spends ~half the time in SHY.",
        "",
    ]
    # fix the accidental "wait" line
    lines = [ln for ln in lines if "wait" not in ln]
    return "\n".join(lines)


def write_risk_matched_report(config: ProjectConfig, payload: dict) -> Path:
    import shutil

    import yaml

    md = render_risk_matched_md(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.reports_dir / "runs" / f"{stamp}_risk_matched"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "risk_matched_payload.json").write_text(json.dumps(payload, indent=2, default=str))
    (run_dir / "risk_matched_benchmarks.md").write_text(md)
    latest = config.reports_dir / "risk_matched_benchmarks.md"
    shutil.copy2(run_dir / "risk_matched_benchmarks.md", latest)
    with (run_dir / "config_snapshot.yaml").open("w") as f:
        yaml.safe_dump(config.raw, f, sort_keys=False)
    return latest
