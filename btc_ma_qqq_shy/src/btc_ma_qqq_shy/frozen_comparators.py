"""Frozen traditional-info comparator (QQQ trend + VIX) and OOS proposition tracker."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import ProjectConfig
from .data import load_adj_close
from .diagnostics import _ensure_symbols, _load_symbol
from .metrics import summary_stats
from .oos_ledger import ledger_path, oos_cutoff
from .reconciliation import (
    fetch_bitfinex_btc,
    lean_sma,
    qc_weekly_signals,
    simulate_from_weekly_signal,
    week_start_equity_dates,
)
from .risk_matched import _ann_vol, _sharpe


def _frozen_comparator_spec(config: ProjectConfig) -> dict:
    spec = config.raw.get("comparators_frozen", {}).get("qqq_trend_vix_v1", {})
    return {
        "id": spec.get("id", "QQQ200_VIX20_v1"),
        "qqq_sma_window": int(spec.get("qqq_sma_window", 200)),
        "vix_threshold": float(spec.get("vix_threshold", 20.0)),
        "logic": spec.get("logic", "all_required"),
        "description": spec.get(
            "description",
            "QQQ > SMA200 AND VIX < 20 at prior session → QQQ else SHY",
        ),
    }


def _weekly_signal_from_daily_mask(
    mask: pd.Series,
    etf_cal: pd.DatetimeIndex,
    week_starts: pd.DatetimeIndex,
    t0: pd.Timestamp,
) -> pd.Series:
    daily = mask.reindex(etf_cal)
    rows = []
    for ws in week_starts:
        prior = etf_cal[etf_cal < ws]
        if len(prior) == 0:
            continue
        d = prior[-1]
        if pd.isna(daily.loc[d]):
            continue
        rows.append((pd.Timestamp(ws), bool(daily.loc[d])))
    sig = pd.Series({ws: v for ws, v in rows}, dtype="boolean")
    return sig[sig.index >= t0]


def _discovery_vol_matched_w(
    strat: pd.Series,
    q: pd.Series,
    h: pd.Series,
    cutoff: pd.Timestamp,
) -> float:
    idx = strat.index
    s = strat.loc[idx[0]:cutoff].dropna()
    qd = q.reindex(s.index).fillna(0.0)
    hd = h.reindex(s.index).fillna(0.0)
    target = _ann_vol(s)
    grid = np.linspace(0, 1, 101)
    vols = np.array([_ann_vol(ww * qd + (1 - ww) * hd) for ww in grid])
    return float(grid[int(np.argmin(np.abs(vols - target)))])


def _pack(label: str, r: pd.Series, occ: float) -> dict:
    st = summary_stats(r)
    return {
        "label": label,
        "cagr": st.get("cagr"),
        "sharpe": _sharpe(r),
        "ann_vol": st.get("ann_vol"),
        "max_dd": st.get("max_drawdown"),
        "final_nav": st.get("final_nav"),
        "pct_qqq": occ,
    }


def run_comparator_audit(config: ProjectConfig) -> dict[str, Any]:
    """Discovery-sample audit: BTC vs frozen QQQ trend + VIX combo and components."""
    spec = _frozen_comparator_spec(config)
    _ensure_symbols(config, ["^VIX"])
    prices = load_adj_close(config)
    bf = fetch_bitfinex_btc(config)
    qqq = prices["QQQ"].reindex(prices[["QQQ", "SHY"]].dropna().index)
    shy = prices["SHY"].reindex(qqq.index)
    etf_cal = qqq.dropna().index
    week_starts = week_start_equity_dates(etf_cal)
    vix = _load_symbol(config, "^VIX").reindex(etf_cal).ffill()

    t0 = pd.Timestamp("2014-11-05")
    cutoff = oos_cutoff(config)

    btc_sig = qc_weekly_signals(bf["Close"].astype(float), week_starts)
    btc_sig = btc_sig.dropna(subset=["risk_on"])
    btc_sig = btc_sig[btc_sig["week_start"] >= t0]
    signal_btc = btc_sig.set_index("week_start")["risk_on"].astype("boolean")

    sma_n = spec["qqq_sma_window"]
    vix_thr = spec["vix_threshold"]
    sma = lean_sma(qqq, sma_n)
    qqq_trend_on = qqq > sma
    vix_low = vix < vix_thr
    if spec["logic"] == "all_required":
        combo_on = qqq_trend_on & vix_low
    else:
        combo_on = qqq_trend_on | vix_low

    signal_qqq200 = _weekly_signal_from_daily_mask(qqq_trend_on, etf_cal, week_starts, t0)
    signal_vix = _weekly_signal_from_daily_mask(vix_low, etf_cal, week_starts, t0)
    signal_combo = _weekly_signal_from_daily_mask(combo_on, etf_cal, week_starts, t0)

    def sim(sig: pd.Series) -> tuple[pd.Series, pd.Series]:
        return simulate_from_weekly_signal(sig, qqq, shy, fill="close", cost_bps_rt=0.0, use_adj=True)

    ret_btc, pos_btc = sim(signal_btc)
    ret_q200, pos_q200 = sim(signal_qqq200)
    ret_vix, pos_vix = sim(signal_vix)
    ret_combo, pos_combo = sim(signal_combo)

    t1 = etf_cal.max()
    idx = ret_btc.loc[t0:t1].dropna().iloc[1:].index
    s_btc = ret_btc.reindex(idx).fillna(0.0)
    q = qqq.pct_change().reindex(idx).fillna(0.0)
    h = shy.pct_change().reindex(idx).fillna(0.0)

    w_vol = _discovery_vol_matched_w(s_btc, q, h, cutoff)
    static = w_vol * q + (1 - w_vol) * h

    # Discovery slice only (pre-cutoff)
    disc_idx = idx[idx <= cutoff]
    rows_full = [
        _pack("BTC_timing", s_btc.reindex(idx).fillna(0.0), float((pos_btc.reindex(idx) == "QQQ").mean())),
        _pack(
            f"QQQ_{sma_n}DMA_only",
            ret_q200.reindex(idx).fillna(0.0),
            float((pos_q200.reindex(idx) == "QQQ").mean()),
        ),
        _pack(
            f"VIX_lt_{vix_thr:.0f}_only",
            ret_vix.reindex(idx).fillna(0.0),
            float((pos_vix.reindex(idx) == "QQQ").mean()),
        ),
        _pack(
            f"QQQ{sma_n}DMA_VIX{int(vix_thr)}_combo",
            ret_combo.reindex(idx).fillna(0.0),
            float((pos_combo.reindex(idx) == "QQQ").mean()),
        ),
        _pack("vol_matched_static", static, w_vol),
    ]
    rows_disc = [
        _pack("BTC_timing", s_btc.reindex(disc_idx).fillna(0.0), float((pos_btc.reindex(disc_idx) == "QQQ").mean())),
        _pack(
            f"QQQ_{sma_n}DMA_only",
            ret_q200.reindex(disc_idx).fillna(0.0),
            float((pos_q200.reindex(disc_idx) == "QQQ").mean()),
        ),
        _pack(
            f"VIX_lt_{vix_thr:.0f}_only",
            ret_vix.reindex(disc_idx).fillna(0.0),
            float((pos_vix.reindex(disc_idx) == "QQQ").mean()),
        ),
        _pack(
            f"QQQ{sma_n}DMA_VIX{int(vix_thr)}_combo",
            ret_combo.reindex(disc_idx).fillna(0.0),
            float((pos_combo.reindex(disc_idx) == "QQQ").mean()),
        ),
        _pack("vol_matched_static", static.reindex(disc_idx).fillna(0.0), w_vol),
    ]

    btc = rows_full[0]
    combo = rows_full[3]
    edge = {
        "cagr_pp": 100 * (btc["cagr"] - combo["cagr"]),
        "sharpe_diff": btc["sharpe"] - combo["sharpe"],
        "maxdd_pp": 100 * (btc["max_dd"] - combo["max_dd"]),
    }
    if edge["sharpe_diff"] > 0.12:
        judgment = "BTC_BEATS_FROZEN_TRADITIONAL_COMBO"
    elif edge["sharpe_diff"] > -0.05:
        judgment = "TRADITIONAL_COMBO_SIMILAR_TO_BTC"
    else:
        judgment = "TRADITIONAL_COMBO_BEATS_BTC_ON_RISK_ADJ"

    # Signal agreement
    align = pd.DataFrame(
        {
            "btc": signal_btc,
            "combo": signal_combo,
            "qqq200": signal_qqq200,
            "vix": signal_vix,
        }
    ).dropna()
    agree_btc_combo = float((align["btc"] == align["combo"]).mean()) if len(align) else np.nan

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "return_basis": "yahoo_adj_close_total_return",
        "sample_full": {"t0": str(t0.date()), "t1": str(t1.date())},
        "sample_discovery": {"t0": str(t0.date()), "t1": str(cutoff.date())},
        "frozen_comparator": spec,
        "discovery_vol_matched_w_qqq": w_vol,
        "comparisons_full": rows_full,
        "comparisons_discovery": rows_disc,
        "btc_vs_combo": edge,
        "judgment": judgment,
        "weekly_signal_agreement_btc_vs_combo": agree_btc_combo,
        "interpretation": (
            "Combo encodes trend + vol regime without BTC. "
            "If BTC ≈ combo, BTC may be a bundled traditional filter; "
            "if BTC >> combo on risk-adj, BTC adds orthogonal timing."
        ),
    }


def _proposition_stats(
    weeks: pd.DataFrame,
    *,
    label: str,
    w_vol: float,
) -> dict[str, Any]:
    """Compute ①②③ on a weekly table with signal, qqq_ret, shy_ret, strategy_ret."""
    if weeks.empty:
        return {"label": label, "n_weeks": 0, "status": "NO_DATA"}

    w = weeks.copy()
    w["spread"] = w["qqq_total_return"] - w["shy_total_return"]
    on = w[w["signal"] == 1]
    off = w[w["signal"] == 0]

    # ① exposure value
    p1_on_spread = float(on["spread"].mean()) if len(on) else np.nan
    p1_off_spread = float(off["spread"].mean()) if len(off) else np.nan
    p1_on_win_rate = float((on["spread"] > 0).mean()) if len(on) else np.nan

    # ② risk-off: QQQ behavior when OFF vs ON
    qqq_on_vol = float(on["qqq_total_return"].std(ddof=1)) if len(on) > 1 else np.nan
    qqq_off_vol = float(off["qqq_total_return"].std(ddof=1)) if len(off) > 1 else np.nan
    qqq_off_neg_frac = float((off["qqq_total_return"] < 0).mean()) if len(off) else np.nan
    qqq_on_neg_frac = float((on["qqq_total_return"] < 0).mean()) if len(on) else np.nan
    if len(off) >= 3:
        qqq_off_tail = float(off["qqq_total_return"].quantile(0.10))
        qqq_on_tail = float(on["qqq_total_return"].quantile(0.10)) if len(on) >= 3 else np.nan
    else:
        qqq_off_tail = qqq_on_tail = np.nan

    # ③ active vs vol-matched static (weekly)
    w["static_ret"] = w_vol * w["qqq_total_return"] + (1 - w_vol) * w["shy_total_return"]
    w["active"] = w["strategy_return"] - w["static_ret"]
    p3_cum_active = float((1 + w["active"]).prod() - 1.0)
    p3_mean_active = float(w["active"].mean())
    p3_active_win = float((w["active"] > 0).mean())

    n = int(len(w))
    status = "INSUFFICIENT_OOS" if n < 8 else "TRACKING"

    return {
        "label": label,
        "n_weeks": n,
        "n_on": int(len(on)),
        "n_off": int(len(off)),
        "status": status,
        "proposition_1_risk_on": {
            "mean_qqq_minus_shy_when_on": p1_on_spread,
            "mean_qqq_minus_shy_when_off": p1_off_spread,
            "win_rate_qqq_beats_shy_when_on": p1_on_win_rate,
            "passes": bool(p1_on_spread > 0) if np.isfinite(p1_on_spread) else False,
        },
        "proposition_2_risk_off": {
            "qqq_week_vol_when_off": qqq_off_vol,
            "qqq_week_vol_when_on": qqq_on_vol,
            "qqq_neg_frac_when_off": qqq_off_neg_frac,
            "qqq_neg_frac_when_on": qqq_on_neg_frac,
            "qqq_10pct_tail_when_off": qqq_off_tail,
            "qqq_10pct_tail_when_on": qqq_on_tail,
            "passes": bool(
                np.isfinite(qqq_off_vol)
                and np.isfinite(qqq_on_vol)
                and qqq_off_vol > qqq_on_vol
                and qqq_off_neg_frac > qqq_on_neg_frac
            ),
        },
        "proposition_3_active_vs_static": {
            "vol_matched_w_qqq": w_vol,
            "cum_active_return": p3_cum_active,
            "mean_weekly_active": p3_mean_active,
            "active_win_rate": p3_active_win,
            "passes": bool(p3_cum_active > 0),
        },
    }


def _weekly_table_from_signals(
    signal: pd.Series,
    qqq: pd.Series,
    shy: pd.Series,
    etf_cal: pd.DatetimeIndex,
    week_starts: pd.DatetimeIndex,
    t0: pd.Timestamp,
    t1: pd.Timestamp,
) -> pd.DataFrame:
    all_ws = [pd.Timestamp(w) for w in week_starts]
    rows = []
    for i, ws in enumerate(all_ws):
        if ws < t0 or ws > t1:
            continue
        if ws not in signal.index or pd.isna(signal.loc[ws]):
            continue
        sig = int(bool(signal.loc[ws]))
        if i + 1 >= len(all_ws):
            continue
        end = all_ws[i + 1]
        days = etf_cal[(etf_cal >= ws) & (etf_cal < end)]
        if len(days) == 0:
            continue
        qqq_r = float((1 + qqq.pct_change().reindex(days).fillna(0.0)).prod() - 1.0)
        shy_r = float((1 + shy.pct_change().reindex(days).fillna(0.0)).prod() - 1.0)
        strat_r = qqq_r if sig else shy_r
        rows.append(
            {
                "week_id": str(ws.date()),
                "signal": sig,
                "qqq_total_return": qqq_r,
                "shy_total_return": shy_r,
                "strategy_return": strat_r,
            }
        )
    return pd.DataFrame(rows)


def run_oos_propositions(config: ProjectConfig) -> dict[str, Any]:
    """Track three OOS propositions on discovery baseline + frozen OOS ledger."""
    prices = load_adj_close(config)
    bf = fetch_bitfinex_btc(config)
    qqq = prices["QQQ"].reindex(prices[["QQQ", "SHY"]].dropna().index)
    shy = prices["SHY"].reindex(qqq.index)
    etf_cal = qqq.dropna().index
    week_starts = week_start_equity_dates(etf_cal)
    cutoff = oos_cutoff(config)
    t0 = pd.Timestamp("2014-11-05")

    btc_sig = qc_weekly_signals(bf["Close"].astype(float), week_starts)
    btc_sig = btc_sig.dropna(subset=["risk_on"])
    btc_sig = btc_sig[btc_sig["week_start"] >= t0]
    signal_btc = btc_sig.set_index("week_start")["risk_on"].astype("boolean")

    ret_btc, _ = simulate_from_weekly_signal(
        signal_btc, qqq, shy, fill="close", cost_bps_rt=0.0, use_adj=True
    )
    t1 = etf_cal.max()
    idx = ret_btc.loc[t0:t1].dropna().iloc[1:].index
    q = qqq.pct_change().reindex(idx).fillna(0.0)
    h = shy.pct_change().reindex(idx).fillna(0.0)
    s_btc = ret_btc.reindex(idx).fillna(0.0)
    w_vol = _discovery_vol_matched_w(s_btc, q, h, cutoff)

    discovery_weeks = _weekly_table_from_signals(
        signal_btc, qqq, shy, etf_cal, week_starts, t0, cutoff
    )
    disc_stats = _proposition_stats(discovery_weeks, label="discovery_pre_cutoff", w_vol=w_vol)

    # OOS from ledger (completed weeks only)
    ledger = pd.read_csv(ledger_path(config)) if ledger_path(config).exists() else pd.DataFrame()
    oos_stats = {"label": "frozen_oos", "n_weeks": 0, "status": "NO_LEDGER_ROWS"}
    if len(ledger):
        oos = ledger.dropna(subset=["strategy_return"]).copy()
        oos["signal"] = oos["signal"].astype(int)
        oos_stats = _proposition_stats(oos, label="frozen_oos_ledger", w_vol=w_vol)

    # Combo comparator propositions on same OOS weeks (signal from combo rule)
    spec = _frozen_comparator_spec(config)
    _ensure_symbols(config, ["^VIX"])
    vix = _load_symbol(config, "^VIX").reindex(etf_cal).ffill()
    sma = lean_sma(qqq, spec["qqq_sma_window"])
    combo_on = (qqq > sma) & (vix < spec["vix_threshold"])
    signal_combo = _weekly_signal_from_daily_mask(combo_on, etf_cal, week_starts, t0)
    combo_disc = _weekly_table_from_signals(
        signal_combo, qqq, shy, etf_cal, week_starts, t0, cutoff
    )
    combo_disc_stats = _proposition_stats(combo_disc, label="combo_discovery", w_vol=w_vol)

    combo_oos_weeks = _weekly_table_from_signals(
        signal_combo, qqq, shy, etf_cal, week_starts, cutoff, etf_cal.max()
    )
    combo_oos_stats = _proposition_stats(
        combo_oos_weeks.dropna(subset=["strategy_return"]),
        label="combo_oos_weeks",
        w_vol=w_vol,
    )

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "oos_cutoff": str(cutoff.date()),
        "discovery_vol_matched_w_qqq_frozen": w_vol,
        "frozen_comparator": _frozen_comparator_spec(config),
        "propositions": {
            "discovery_btc": disc_stats,
            "oos_btc": oos_stats,
            "discovery_combo": combo_disc_stats,
            "oos_combo": combo_oos_stats,
        },
        "oos_tracking_guide": {
            "1_exposure_value": "BTC=ON weeks: QQQ should beat SHY (mean spread > 0)",
            "2_risk_off_downside": "BTC=OFF weeks: QQQ vol/neg-fraction worse than ON weeks",
            "3_active_return": "Strategy beats vol-matched static (cum active > 0)",
            "min_oos_weeks_for_confidence": 8,
        },
        "ledger_path": str(ledger_path(config)),
        "ledger_n_rows": int(len(ledger)) if len(ledger) else 0,
    }


def render_comparator_md(p: dict) -> str:
    spec = p["frozen_comparator"]
    lines = [
        "# Frozen Traditional Comparator: QQQ Trend + VIX",
        "",
        f"Rule id: **`{spec['id']}`** — {spec['description']}",
        f"Logic: `{spec['logic']}` | VIX threshold: `{spec['vix_threshold']}` | QQQ SMA: `{spec['qqq_sma_window']}`",
        f"Judgment: **`{p['judgment']}`**",
        "",
        f"Discovery vol-matched w_QQQ (frozen at cutoff): `{p['discovery_vol_matched_w_qqq']:.2f}`",
        f"BTC vs combo weekly signal agreement: `{100*p['weekly_signal_agreement_btc_vs_combo']:.1f}%`",
        "",
        "## Full sample (`" + p["sample_full"]["t0"] + "` → `" + p["sample_full"]["t1"] + "`)",
        "",
        "| Portfolio | CAGR | Sharpe | Vol | MaxDD | w_QQQ |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in p["comparisons_full"]:
        lines.append(
            f"| {r['label']} | {100*r['cagr']:.2f}% | {r['sharpe']:.3f} | "
            f"{100*r['ann_vol']:.2f}% | {100*r['max_dd']:.2f}% | {r['pct_qqq']:.2f} |"
        )
    e = p["btc_vs_combo"]
    lines += [
        "",
        f"BTC vs combo: ΔCAGR `{e['cagr_pp']:.2f}` pp, ΔSharpe `{e['sharpe_diff']:.3f}`, ΔMaxDD `{e['maxdd_pp']:.2f}` pp",
        "",
        "## Discovery only (pre-OOS cutoff)",
        "",
        "| Portfolio | CAGR | Sharpe | Vol | MaxDD | w_QQQ |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in p["comparisons_discovery"]:
        lines.append(
            f"| {r['label']} | {100*r['cagr']:.2f}% | {r['sharpe']:.3f} | "
            f"{100*r['ann_vol']:.2f}% | {100*r['max_dd']:.2f}% | {r['pct_qqq']:.2f} |"
        )
    lines += ["", p["interpretation"], ""]
    return "\n".join(lines)


def render_propositions_md(p: dict) -> str:
    lines = [
        "# OOS Proposition Tracker",
        "",
        f"OOS cutoff: `{p['oos_cutoff']}` | Frozen w_QQQ: `{p['discovery_vol_matched_w_qqq_frozen']:.2f}`",
        f"Ledger: `{p['ledger_path']}` ({p['ledger_n_rows']} rows)",
        "",
        "Three propositions to watch as OOS accumulates:",
        "",
        "1. **Risk-on exposure value** — BTC=ON: QQQ beats SHY?",
        "2. **Risk-off downside** — BTC=OFF: QQQ higher vol / worse tails?",
        "3. **Active vs vol-matched static** — cumulative active return > 0?",
        "",
    ]
    for key in ["discovery_btc", "oos_btc", "discovery_combo", "oos_combo"]:
        s = p["propositions"][key]
        lines += [
            f"## `{s['label']}` (n={s.get('n_weeks', 0)}, status={s.get('status', '?')})",
            "",
        ]
        if s.get("n_weeks", 0) == 0:
            lines.append("_No data yet._", "")
            continue
        p1 = s["proposition_1_risk_on"]
        p2 = s["proposition_2_risk_off"]
        p3 = s["proposition_3_active_vs_static"]
        lines += [
            "| Prop | Metric | Value | Pass? |",
            "|---|---|---|---|",
            f"| ① ON spread (QQQ−SHY) | mean when ON | {100*p1['mean_qqq_minus_shy_when_on']:.3f}% | "
            f"{'✓' if p1['passes'] else '✗'} |",
            f"| ① | win rate QQQ>SHY when ON | {100*p1['win_rate_qqq_beats_shy_when_on']:.1f}% | |",
            f"| ② | QQQ week vol OFF vs ON | {100*p2['qqq_week_vol_when_off']:.2f}% vs "
            f"{100*p2['qqq_week_vol_when_on']:.2f}% | "
            f"{'✓' if p2['passes'] else '✗'} |",
            f"| ② | QQQ neg week frac OFF vs ON | {100*p2['qqq_neg_frac_when_off']:.1f}% vs "
            f"{100*p2['qqq_neg_frac_when_on']:.1f}% | |",
            f"| ② | QQQ 10% tail OFF vs ON | {100*p2['qqq_10pct_tail_when_off']:.2f}% vs "
            f"{100*p2['qqq_10pct_tail_when_on']:.2f}% | |",
            f"| ③ | cum active vs static | {100*p3['cum_active_return']:.3f}% | "
            f"{'✓' if p3['passes'] else '✗'} |",
            f"| ③ | mean weekly active | {100*p3['mean_weekly_active']:.3f}% | |",
            "",
        ]
    return "\n".join(lines)


def write_comparator_report(config: ProjectConfig, payload: dict) -> Path:
    import shutil
    import yaml

    md = render_comparator_md(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.reports_dir / "runs" / f"{stamp}_traditional_combo"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "traditional_combo_payload.json").write_text(json.dumps(payload, indent=2, default=str))
    (run_dir / "traditional_combo.md").write_text(md)
    with (run_dir / "config_snapshot.yaml").open("w") as f:
        yaml.safe_dump(config.raw, f, sort_keys=False)
    latest = config.reports_dir / "traditional_combo.md"
    shutil.copy2(run_dir / "traditional_combo.md", latest)
    return latest


def write_propositions_report(config: ProjectConfig, payload: dict) -> Path:
    import shutil
    import yaml

    md = render_propositions_md(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.reports_dir / "runs" / f"{stamp}_oos_propositions"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "oos_propositions_payload.json").write_text(json.dumps(payload, indent=2, default=str))
    (run_dir / "oos_propositions.md").write_text(md)
    with (run_dir / "config_snapshot.yaml").open("w") as f:
        yaml.safe_dump(config.raw, f, sort_keys=False)
    latest = config.reports_dir / "oos_propositions.md"
    shutil.copy2(run_dir / "oos_propositions.md", latest)
    return latest
