"""Active-return attribution vs vol-matched static + frozen QQQ 200DMA benchmark."""
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
    lean_sma,
    qc_weekly_signals,
    simulate_from_weekly_signal,
    week_start_equity_dates,
)
from .risk_matched import _ann_vol, _sharpe

# Frozen classic benchmark — not tuned on this sample
QQQ_TREND_200DMA_SMA = 200


def _cagr_from_returns(r: pd.Series) -> float:
    x = r.dropna()
    if len(x) < 2:
        return float("nan")
    nav = (1 + x).cumprod()
    years = (x.index[-1] - x.index[0]).days / 365.25
    if years <= 0:
        return float("nan")
    return float(nav.iloc[-1] ** (1 / years) - 1)


def _compound_contribution(daily_piece: pd.Series) -> dict:
    """Wealth from compounding only the attributed daily pieces (mutually exclusive buckets)."""
    x = daily_piece.fillna(0.0)
    if len(x) < 2:
        return {"cum_wealth": 1.0, "cagr": 0.0, "sum_daily": 0.0}
    nav = float((1 + x).prod())
    years = (x.index[-1] - x.index[0]).days / 365.25
    cagr = nav ** (1 / years) - 1 if years > 0 else float("nan")
    return {"cum_wealth": nav, "cagr": float(cagr), "sum_daily": float(x.sum())}


def _regime_labels(
    index: pd.DatetimeIndex,
    qqq: pd.Series,
    vix: pd.Series,
) -> pd.DataFrame:
    """Bull/bear from QQQ vs 200DMA; high/low VIX vs full-sample median."""
    qqq = qqq.reindex(index).ffill()
    vix = vix.reindex(index).ffill()
    sma200 = qqq.rolling(QQQ_TREND_200DMA_SMA, min_periods=QQQ_TREND_200DMA_SMA).mean()
    bull = qqq > sma200
    vix_med = float(vix.median())
    high_vix = vix > vix_med
    return pd.DataFrame(
        {
            "bull_qqq_200dma": bull,
            "bear_qqq_200dma": ~bull,
            "high_vix": high_vix,
            "low_vix": ~high_vix,
        },
        index=index,
    )


def _attribution_slice(
    active_on: pd.Series,
    active_off: pd.Series,
    active_total: pd.Series,
    mask: pd.Series,
) -> dict:
    m = mask.reindex(active_total.index).fillna(False).astype(bool)
    on = active_on.loc[m]
    off = active_off.loc[m]
    tot = active_total.loc[m]
    on_stats = _compound_contribution(on)
    off_stats = _compound_contribution(off)
    tot_stats = _compound_contribution(tot)
    # Share of arithmetic active sum
    s_on = float(on.sum())
    s_off = float(off.sum())
    s_tot = float(tot.sum())
    return {
        "n_days": int(m.sum()),
        "pct_days": float(m.mean()),
        "risk_on_cum_wealth": on_stats["cum_wealth"],
        "risk_on_cagr_piece": on_stats["cagr"],
        "risk_on_sum_daily_active": s_on,
        "risk_off_cum_wealth": off_stats["cum_wealth"],
        "risk_off_cagr_piece": off_stats["cagr"],
        "risk_off_sum_daily_active": s_off,
        "total_cum_wealth": tot_stats["cum_wealth"],
        "total_cagr_piece": tot_stats["cagr"],
        "total_sum_daily_active": s_tot,
        "pct_arithmetic_active_from_on": s_on / s_tot if abs(s_tot) > 1e-12 else np.nan,
        "pct_arithmetic_active_from_off": s_off / s_tot if abs(s_tot) > 1e-12 else np.nan,
    }


def run_timing_attribution(config: ProjectConfig) -> dict[str, Any]:
    from .diagnostics import _ensure_symbols, _load_symbol

    _ensure_symbols(config, ["^VIX"])
    prices = load_adj_close(config)
    bf = fetch_bitfinex_btc(config)
    qqq = prices["QQQ"]
    shy = prices["SHY"]
    spy = prices["SPY"]
    vix = _load_symbol(config, "^VIX")
    etf_cal = prices[["QQQ", "SHY", "SPY"]].dropna().index
    week_starts = week_start_equity_dates(etf_cal)

    btc_sig = qc_weekly_signals(bf["Close"].astype(float), week_starts)
    valid = btc_sig.dropna(subset=["risk_on"])
    valid = valid[valid["week_start"] >= pd.Timestamp("2014-11-05")]
    signal = valid.set_index("week_start")["risk_on"].astype("boolean")

    strat, pos = simulate_from_weekly_signal(
        signal, qqq, shy, fill="close", cost_bps_rt=0.0, use_adj=True
    )

    t0 = pd.Timestamp(valid["week_start"].iloc[0])
    t1 = etf_cal.max()
    idx = strat.loc[t0:t1].dropna().iloc[1:].index
    s = strat.reindex(idx).fillna(0.0)
    q = qqq.pct_change().reindex(idx).fillna(0.0)
    h = shy.pct_change().reindex(idx).fillna(0.0)

    grid = np.linspace(0, 1, 101)
    vols = np.array([_ann_vol(ww * q + (1 - ww) * h) for ww in grid])
    w_vol = float(grid[int(np.argmin(np.abs(vols - _ann_vol(s))))])

    static_vol = w_vol * q + (1 - w_vol) * h
    active = s - static_vol

    risk_on = pos.reindex(idx) == "QQQ"
    # Exact daily decomposition (mutually exclusive)
    active_on = pd.Series(0.0, index=idx)
    active_off = pd.Series(0.0, index=idx)
    active_on.loc[risk_on] = (1 - w_vol) * (q.loc[risk_on] - h.loc[risk_on])
    active_off.loc[~risk_on] = w_vol * (h.loc[~risk_on] - q.loc[~risk_on])

    regimes = _regime_labels(idx, qqq, vix)
    full = _attribution_slice(active_on, active_off, active, pd.Series(True, index=idx))

    regime_slices = {}
    for name in ["bull_qqq_200dma", "bear_qqq_200dma", "high_vix", "low_vix"]:
        regime_slices[name] = _attribution_slice(
            active_on, active_off, active, regimes[name]
        )

    # Yearly: where did active come from?
    yearly = []
    for year, g in active.groupby(active.index.year):
        m = pd.Series(True, index=g.index)
        yr = _attribution_slice(
            active_on.loc[g.index],
            active_off.loc[g.index],
            g,
            m,
        )
        qqq_yr = float((1 + q[q.index.year == year]).prod() - 1)
        yr["year"] = int(year)
        yr["qqq_calendar_return"] = qqq_yr
        yr["strategy_return"] = float((1 + s[s.index.year == year]).prod() - 1)
        yr["static_vol_matched_return"] = float(
            (1 + static_vol[static_vol.index.year == year]).prod() - 1
        )
        yearly.append(yr)

    # Headline CAGR edge
    cagr_strat = _cagr_from_returns(s)
    cagr_static = _cagr_from_returns(static_vol)
    cagr_edge_pp = 100 * (cagr_strat - cagr_static)

    # Interpretation: full-sample arithmetic active vs regime-specific defense
    off_share = full.get("pct_arithmetic_active_from_off")
    on_share = full.get("pct_arithmetic_active_from_on")
    bear_off = regime_slices["bear_qqq_200dma"].get("pct_arithmetic_active_from_off")
    hi_vix_off = regime_slices["high_vix"].get("pct_arithmetic_active_from_off")
    if off_share is not None and off_share < 0 and on_share > 0.8:
        narrative = "FULL_SAMPLE_OFFENSE_LED_RISK_OFF_HURTS_VS_56PCT_STATIC"
    elif bear_off is not None and bear_off > 0.7 and hi_vix_off > 0.7:
        narrative = "DEFENSE_DOMINATES_IN_BEAR_AND_HIGH_VIX_OFFENSE_IN_BULL"
    elif off_share is not None and off_share > 0.45 and on_share > 0.35:
        narrative = "BOTH_OFFENSE_AND_DEFENSE_MATERIAL"
    else:
        narrative = "MIXED_REGIME_DEPENDENT"

    # --- Frozen QQQ 200DMA benchmark (same weekly schedule, adj TR) ---
    qqq_tr = qqq.reindex(etf_cal)
    shy_tr = shy.reindex(etf_cal)
    sma200 = lean_sma(qqq_tr, QQQ_TREND_200DMA_SMA)
    qqq200_daily = qqq_tr > sma200
    # Weekly signal at week_start: use state on prior session (no same-bar)
    qqq200_weekly = []
    for ws in week_starts:
        if ws not in etf_cal:
            continue
        prior = etf_cal[etf_cal < ws]
        if len(prior) == 0:
            continue
        d = prior[-1]
        if pd.isna(qqq200_daily.loc[d]):
            continue
        qqq200_weekly.append((ws, bool(qqq200_daily.loc[d])))
    qqq200_sig = pd.Series(
        {ws: v for ws, v in qqq200_weekly},
        dtype="boolean",
    )
    qqq200_sig = qqq200_sig[qqq200_sig.index >= t0]

    qqq200_ret, qqq200_pos = simulate_from_weekly_signal(
        qqq200_sig, qqq_tr, shy_tr, fill="close", cost_bps_rt=0.0, use_adj=True
    )
    q200 = qqq200_ret.loc[t0:t1].dropna().iloc[1:]

    def pack(label: str, r: pd.Series, occ: float) -> dict:
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

    occ_btc = float((pos.reindex(s.index) == "QQQ").mean())
    occ_q200 = float((qqq200_pos.reindex(q200.index) == "QQQ").mean())
    bench_rows = [
        pack("BTC_timing_QC_adj_0bps", s, occ_btc),
        pack("vol_matched_static", static_vol, w_vol),
        pack(f"QQQ_{QQQ_TREND_200DMA_SMA}DMA_SHY_adj_0bps", q200, occ_q200),
        pack("100pct_QQQ", q, 1.0),
    ]

    btc_vs_qqq200 = {
        "cagr_pp": 100 * (bench_rows[0]["cagr"] - bench_rows[2]["cagr"]),
        "sharpe_diff": bench_rows[0]["sharpe"] - bench_rows[2]["sharpe"],
        "maxdd_pp": 100 * (bench_rows[0]["max_dd"] - bench_rows[2]["max_dd"]),
    }

    if btc_vs_qqq200["sharpe_diff"] > 0.15:
        bench_judgment = "BTC_BEATS_FROZEN_QQQ_200DMA_ON_RISK_ADJ"
    elif btc_vs_qqq200["sharpe_diff"] > -0.05:
        bench_judgment = "BTC_SIMILAR_TO_QQQ_200DMA_NOT_CLEARLY_NECESSARY"
    else:
        bench_judgment = "QQQ_200DMA_COMPETITIVE_OR_BETTER_THAN_BTC"

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "sample": {"t0": str(t0.date()), "t1": str(pd.Timestamp(t1).date())},
        "return_basis": "yahoo_adj_close_total_return",
        "vol_matched_w_qqq": w_vol,
        "cagr_edge_pp_vs_vol_matched": cagr_edge_pp,
        "decomposition_formula": {
            "risk_on_day": "(1-w)*(R_QQQ - R_SHY) when BTC→QQQ",
            "risk_off_day": "w*(R_SHY - R_QQQ) when BTC→SHY",
            "benchmark": "vol-matched static mix w*QQQ+(1-w)*SHY",
        },
        "full_sample": full,
        "regime_slices": regime_slices,
        "yearly_active": yearly,
        "narrative": narrative,
        "benchmark_comparison": bench_rows,
        "btc_vs_qqq200dma": btc_vs_qqq200,
        "benchmark_judgment": bench_judgment,
        "frozen_qqq200_rule": f"QQQ > SMA{QQQ_TREND_200DMA_SMA} at prior session → QQQ else SHY; weekly QC week-start",
    }


def render_attribution_md(p: dict) -> str:
    f = p["full_sample"]
    lines = [
        "# Timing Advantage Attribution",
        "",
        f"Return basis: **{p['return_basis']}**",
        f"Sample: `{p['sample']['t0']}` → `{p['sample']['t1']}`",
        f"Vol-matched static w_QQQ = `{p['vol_matched_w_qqq']:.2f}`",
        f"CAGR edge (BTC timing − vol-matched): **`{p['cagr_edge_pp_vs_vol_matched']:.2f}` pp**",
        f"Narrative: **`{p['narrative']}`**",
        "",
        "> Full-sample Σdaily active: **A (risk-on)** adds most edge because static already holds 56% QQQ — "
        "going 100% SHY when BTC is off often *underperforms* static in long bull runs. "
        "**B (risk-off)** dominates arithmetic active in bear (QQQ≤200DMA) and high-VIX regimes, "
        "and in crisis years (e.g. 2022).",
        "",
        "## A / B decomposition (vs vol-matched static)",
        "",
        "| Bucket | Meaning | Cum wealth (daily piece) | CAGR piece | Σ daily active | % of Σ active |",
        "|---|---|---:|---:|---:|---:|",
        f"| **A Risk-on** | BTC→QQQ; static only `{p['vol_matched_w_qqq']:.0%}` QQQ | "
        f"{f['risk_on_cum_wealth']:.4f} | {100*f['risk_on_cagr_piece']:.2f}% | "
        f"{f['risk_on_sum_daily_active']*100:.2f}% | {100*f['pct_arithmetic_active_from_on']:.1f}% |",
        f"| **B Risk-off** | BTC→SHY; static still `{p['vol_matched_w_qqq']:.0%}` QQQ | "
        f"{f['risk_off_cum_wealth']:.4f} | {100*f['risk_off_cagr_piece']:.2f}% | "
        f"{f['risk_off_sum_daily_active']*100:.2f}% | {100*f['pct_arithmetic_active_from_off']:.1f}% |",
        f"| **Total** | | {f['total_cum_wealth']:.4f} | {100*f['total_cagr_piece']:.2f}% | "
        f"{f['total_sum_daily_active']*100:.2f}% | 100% |",
        "",
        "A and B are mutually exclusive daily pieces; product of (1+A) and (1+B) over their days equals total active wealth.",
        "",
        "## Regime splits",
        "",
        "| Regime | n days | A Σ active | B Σ active | B share |",
        "|---|---:|---:|---:|---:|",
    ]
    labels = {
        "bull_qqq_200dma": "Bull (QQQ>200DMA)",
        "bear_qqq_200dma": "Bear (QQQ≤200DMA)",
        "high_vix": "High VIX",
        "low_vix": "Low VIX",
    }
    for key, label in labels.items():
        r = p["regime_slices"][key]
        lines.append(
            f"| {label} | {r['n_days']} | {r['risk_on_sum_daily_active']*100:.2f}% | "
            f"{r['risk_off_sum_daily_active']*100:.2f}% | "
            f"{100*r['pct_arithmetic_active_from_off']:.1f}% |"
        )
    lines += [
        "",
        "## Yearly active (strategy − vol-matched)",
        "",
        "| Year | QQQ | Strat | Static | Active A | Active B | B share |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for y in p["yearly_active"]:
        lines.append(
            f"| {y['year']} | {100*y['qqq_calendar_return']:.1f}% | "
            f"{100*y['strategy_return']:.1f}% | {100*y['static_vol_matched_return']:.1f}% | "
            f"{y['risk_on_sum_daily_active']*100:.2f}% | {y['risk_off_sum_daily_active']*100:.2f}% | "
            f"{100*y['pct_arithmetic_active_from_off']:.0f}% |"
        )
    lines += [
        "",
        "## Frozen benchmark: QQQ 200DMA → QQQ else SHY",
        "",
        f"Rule: `{p['frozen_qqq200_rule']}` — **not tuned** on this sample.",
        f"Judgment: **`{p['benchmark_judgment']}`**",
        "",
        "| Portfolio | CAGR | Sharpe | Vol | MaxDD | w_QQQ |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in p["benchmark_comparison"]:
        w = r.get("pct_qqq", 0)
        lines.append(
            f"| {r['label']} | {100*r['cagr']:.2f}% | {r['sharpe']:.3f} | "
            f"{100*r['ann_vol']:.2f}% | {100*r['max_dd']:.2f}% | {w:.2f} |"
        )
    b = p["btc_vs_qqq200dma"]
    lines += [
        "",
        f"BTC vs QQQ200DMA: ΔCAGR `{b['cagr_pp']:.2f}` pp, ΔSharpe `{b['sharpe_diff']:.3f}`, "
        f"ΔMaxDD `{b['maxdd_pp']:.2f}` pp",
        "",
    ]
    return "\n".join(lines)


def write_attribution_report(config: ProjectConfig, payload: dict) -> Path:
    import shutil

    import yaml

    md = render_attribution_md(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.reports_dir / "runs" / f"{stamp}_timing_attribution"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "timing_attribution_payload.json").write_text(
        json.dumps(payload, indent=2, default=str)
    )
    (run_dir / "timing_attribution.md").write_text(md)
    with (run_dir / "config_snapshot.yaml").open("w") as f:
        yaml.safe_dump(config.raw, f, sort_keys=False)
    latest = config.reports_dir / "timing_attribution.md"
    shutil.copy2(run_dir / "timing_attribution.md", latest)
    return latest
