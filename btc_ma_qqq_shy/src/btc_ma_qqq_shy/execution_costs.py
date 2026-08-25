"""Costs, next-open execution, and BTC timestamp / look-ahead audit."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from .config import ProjectConfig
from .data import load_adj_close
from .metrics import summary_stats
from .reconciliation import (
    fetch_bitfinex_btc,
    lean_roc,
    lean_sma,
    load_ohlc_symbol,
    qc_weekly_signals,
    simulate_from_weekly_signal,
    week_start_equity_dates,
)


ONE_WAY_BPS = (0, 1, 2, 5, 10)
# Typical quoted half-spreads (research assumptions, not measured tape)
HALF_SPREAD_BPS = {"QQQ": 1.0, "SHY": 2.0}


def _sharpe(r: pd.Series) -> float:
    x = r.dropna()
    if len(x) < 5 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / x.std(ddof=1) * np.sqrt(252))


def candle_close_utc(open_date: pd.Timestamp) -> pd.Timestamp:
    """UTC daily candle opening at open_date 00:00Z closes at next day 00:00Z."""
    return pd.Timestamp(open_date).normalize() + pd.Timedelta(days=1)


def monday_8am_et_as_utc(week_start: pd.Timestamp) -> pd.Timestamp:
    """Approximate Mon 08:00 America/New_York → UTC (handles DST via zoneinfo)."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover
        from backports.zoneinfo import ZoneInfo  # type: ignore

    et = ZoneInfo("America/New_York")
    local = pd.Timestamp(week_start).normalize().to_pydatetime().replace(
        hour=8, minute=0, second=0, tzinfo=et
    )
    return pd.Timestamp(local.astimezone(ZoneInfo("UTC"))).tz_localize(None)


def timestamp_audit_row(
    btc_close: pd.Series,
    week_start: pd.Timestamp,
    *,
    sma_n: int = 50,
    roc_n: int = 20,
) -> dict:
    """
    For one week-start, compare BTC bars visible at Mon 08:00 ET.

    Safe: bar close_utc <= Mon 08:00 ET.
    Canonical QC proxy: last bar with open_date < week_start (Sunday UTC bar).
    Look-ahead trap: Monday UTC bar (open=week_start) — closes Tue 00:00 UTC, NOT visible Mon 8am.
    """
    sma = lean_sma(btc_close, sma_n)
    roc = lean_roc(btc_close, roc_n)
    ws = pd.Timestamp(week_start).normalize()
    decision_utc = monday_8am_et_as_utc(ws)

    # All bars with completed close before decision
    completed = []
    for d in btc_close.dropna().index:
        d = pd.Timestamp(d).normalize()
        close_t = candle_close_utc(d)
        if close_t <= decision_utc:
            completed.append(d)
    if not completed:
        return {"week_start": ws, "ok": False}
    safe_asof = max(completed)
    sun_proxy = btc_close.loc[btc_close.index < ws].index.max() if (btc_close.index < ws).any() else None
    mon_bar = ws if ws in btc_close.index else None

    def sig(asof: Optional[pd.Timestamp]) -> Optional[bool]:
        if asof is None or asof not in sma.index or pd.isna(sma.loc[asof]) or pd.isna(roc.loc[asof]):
            return None
        return bool(float(btc_close.loc[asof]) > float(sma.loc[asof]) and float(roc.loc[asof]) > 0.0)

    safe_sig = sig(safe_asof)
    sun_sig = sig(pd.Timestamp(sun_proxy)) if sun_proxy is not None else None
    # Intentional look-ahead: use Monday open bar as if complete at Mon 8am (INVALID)
    la_sig = sig(mon_bar) if mon_bar is not None else None

    sun_close_utc = candle_close_utc(sun_proxy) if sun_proxy is not None else None
    mon_close_utc = candle_close_utc(mon_bar) if mon_bar is not None else None

    return {
        "week_start": ws,
        "ok": True,
        "decision_utc": decision_utc,
        "safe_asof": safe_asof,
        "safe_close_utc": candle_close_utc(safe_asof),
        "sunday_proxy_asof": sun_proxy,
        "sunday_close_utc": sun_close_utc,
        "monday_bar_open": mon_bar,
        "monday_bar_close_utc": mon_close_utc,
        "sunday_complete_before_mon8et": (
            sun_close_utc is not None and sun_close_utc <= decision_utc
        ),
        "monday_bar_complete_before_mon8et": (
            mon_close_utc is not None and mon_close_utc <= decision_utc
        ),
        "safe_equals_sunday_proxy": (
            sun_proxy is not None and pd.Timestamp(sun_proxy).normalize() == pd.Timestamp(safe_asof).normalize()
        ),
        "signal_safe": safe_sig,
        "signal_sunday_proxy": sun_sig,
        "signal_lookahead_monday_bar": la_sig,
        "hours_sunday_close_before_mon8et": (
            (decision_utc - sun_close_utc).total_seconds() / 3600.0 if sun_close_utc is not None else np.nan
        ),
    }


def run_timestamp_audit(btc_close: pd.Series, week_starts: pd.DatetimeIndex) -> dict:
    rows = [timestamp_audit_row(btc_close, ws) for ws in week_starts]
    frame = pd.DataFrame([r for r in rows if r.get("ok")])
    if frame.empty:
        return {"n": 0}
    return {
        "n_weeks": int(len(frame)),
        "pct_sunday_complete_before_mon8et": float(frame["sunday_complete_before_mon8et"].mean()),
        "pct_monday_bar_complete_before_mon8et": float(frame["monday_bar_complete_before_mon8et"].mean()),
        "pct_safe_equals_sunday_proxy": float(frame["safe_equals_sunday_proxy"].mean()),
        "median_hours_sunday_close_before_mon8et": float(frame["hours_sunday_close_before_mon8et"].median()),
        "pct_signal_safe_equals_sunday": float(
            (frame["signal_safe"] == frame["signal_sunday_proxy"]).mean()
        ),
        "pct_signal_safe_equals_lookahead_monday": float(
            (frame["signal_safe"] == frame["signal_lookahead_monday_bar"]).dropna().mean()
        )
        if frame["signal_lookahead_monday_bar"].notna().any()
        else np.nan,
        "look_ahead_judgment": (
            "SUNDAY_UTC_CANDLE_SAFE_AT_MON_08ET__MONDAY_BAR_NOT_VISIBLE"
            if frame["sunday_complete_before_mon8et"].all()
            and not frame["monday_bar_complete_before_mon8et"].any()
            else "NEEDS_MANUAL_REVIEW"
        ),
        "sample_rows": frame.head(8).to_dict(orient="records"),
    }


def cost_sweep_qc_proxy(config: ProjectConfig) -> dict[str, Any]:
    """QC week-start Bitfinex signals + next-open fill; sweep one-way bps + half-spreads."""
    bf = fetch_bitfinex_btc(config)
    prices = load_adj_close(config)
    qqq_ohlc = load_ohlc_symbol(config, "QQQ")
    shy_ohlc = load_ohlc_symbol(config, "SHY")
    etf_cal = prices[["QQQ", "SHY"]].dropna().index
    week_starts = week_start_equity_dates(etf_cal)

    sigs = qc_weekly_signals(bf["Close"].astype(float), week_starts)
    valid = sigs.dropna(subset=["risk_on"]).copy()
    valid = valid[valid["week_start"] >= pd.Timestamp(config.raw["data"]["audit_start"])]
    signal = valid.set_index("week_start")["risk_on"].astype("boolean")

    qqq_adj = prices["QQQ"]
    shy_adj = prices["SHY"]
    qqq_cl = qqq_ohlc["Close"].astype(float)
    shy_cl = shy_ohlc["Close"].astype(float)
    qqq_op = qqq_ohlc["Open"].astype(float)
    shy_op = shy_ohlc["Open"].astype(float)

    t0 = max(pd.Timestamp(valid["week_start"].iloc[0]), pd.Timestamp("2014-11-05"))
    t1 = etf_cal.max()

    # Dividend / total-return gap: Adj vs Close buy&hold SHY/QQQ
    def bh(series: pd.Series) -> dict:
        r = series.reindex(etf_cal).pct_change().loc[t0:t1].dropna().iloc[1:]
        return summary_stats(r)

    tr_gap = {
        "QQQ_adj": bh(qqq_adj),
        "QQQ_close": bh(qqq_cl),
        "SHY_adj": bh(shy_adj),
        "SHY_close": bh(shy_cl),
        "SHY_cagr_adj_minus_close_pp": 100
        * (bh(shy_adj).get("cagr", np.nan) - bh(shy_cl).get("cagr", np.nan)),
        "QQQ_cagr_adj_minus_close_pp": 100
        * (bh(qqq_adj).get("cagr", np.nan) - bh(qqq_cl).get("cagr", np.nan)),
    }

    # Holiday / week-start not Monday
    ws = pd.DatetimeIndex(valid["week_start"])
    holiday_stats = {
        "n_week_starts": int(len(ws)),
        "pct_monday": float((ws.dayofweek == 0).mean()),
        "n_non_monday_week_starts": int((ws.dayofweek != 0).sum()),
        "non_monday_examples": [str(d.date()) for d in ws[ws.dayofweek != 0][:12]],
    }

    ts_audit = run_timestamp_audit(bf["Close"].astype(float), pd.DatetimeIndex(valid["week_start"]))

    rows = []
    for ow in ONE_WAY_BPS:
        # round-trip = 2 * one-way; plus optional half-spreads on each switch leg
        rt = 2.0 * ow
        for use_spread in (False, True):
            extra = 0.0
            if use_spread:
                # each switch pays half-spread on exit + half-spread on entry (approx avg)
                extra = HALF_SPREAD_BPS["QQQ"] + HALF_SPREAD_BPS["SHY"]  # one-way each side once
            cost_rt = rt + (extra if use_spread else 0.0)
            # simulate uses round-trip bps on switch days
            rets, pos = simulate_from_weekly_signal(
                signal,
                qqq_adj,
                shy_adj,
                fill="open",
                cost_bps_rt=cost_rt,
                use_adj=True,
                qqq_close=qqq_cl,
                shy_close=shy_cl,
                qqq_open=qqq_op,
                shy_open=shy_op,
            )
            # Prefer Adj for TR; open-fill skipped when use_adj — also run Close+open
            rets_co, pos2 = simulate_from_weekly_signal(
                signal,
                qqq_adj,
                shy_adj,
                fill="open",
                cost_bps_rt=cost_rt,
                use_adj=False,
                qqq_close=qqq_cl,
                shy_close=shy_cl,
                qqq_open=qqq_op,
                shy_open=shy_op,
            )
            x = rets_co.loc[t0:t1].dropna().iloc[1:]
            st = summary_stats(x)
            switches = int(pos2.ne(pos2.shift(1)).loc[t0:t1].sum())
            rows.append(
                {
                    "one_way_bps": ow,
                    "include_half_spreads": use_spread,
                    "effective_rt_bps": cost_rt,
                    "n_switches": switches,
                    "sharpe": _sharpe(x),
                    "cagr": st.get("cagr"),
                    "ann_vol": st.get("ann_vol"),
                    "max_dd": st.get("max_drawdown"),
                    "final_nav": st.get("final_nav"),
                    "engine": "close_openfill_QC_weekstart_bitfinex",
                }
            )

    # Baseline 0bps adj c2c for reference
    rets0, _ = simulate_from_weekly_signal(
        signal, qqq_adj, shy_adj, fill="close", cost_bps_rt=0.0, use_adj=True
    )
    x0 = rets0.loc[t0:t1].dropna().iloc[1:]

    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "sample": {"t0": str(t0.date()), "t1": str(pd.Timestamp(t1).date())},
        "assumptions": {
            "one_way_bps_grid": list(ONE_WAY_BPS),
            "half_spread_bps": HALF_SPREAD_BPS,
            "execution": "QC week-start Bitfinex signal; Open→Close on switch day; then C2C",
            "note": "Half-spreads are research assumptions (not historical NBBO).",
        },
        "holiday_week_starts": holiday_stats,
        "total_return_vs_price": tr_gap,
        "timestamp_audit": ts_audit,
        "cost_sweep": rows,
        "baseline_adj_c2c_0bps": {
            "sharpe": _sharpe(x0),
            **{k: summary_stats(x0).get(k) for k in ("cagr", "ann_vol", "max_drawdown", "final_nav")},
        },
        "judgment": _cost_judgment(rows, ts_audit),
    }
    return payload


def _cost_judgment(rows: list[dict], ts_audit: dict) -> str:
    by = {(r["one_way_bps"], r["include_half_spreads"]): r for r in rows}
    s0 = by[(0, False)]["sharpe"]
    s5 = by[(5, False)]["sharpe"]
    s10s = by[(10, True)]["sharpe"]
    la = ts_audit.get("look_ahead_judgment", "")
    if "SAFE" not in la:
        return "TIMESTAMP_LOOKAHEAD_NEEDS_REVIEW"
    if s10s > 0.9 and s5 > 1.0:
        return "EDGE_SURVIVES_REALISTIC_COSTS_UNDER_LOCAL_ENGINE__STILL_NOT_QC_0_838"
    if s5 > 0.8:
        return "EDGE_PARTIALLY_SURVIVES_COSTS_SENSITIVE"
    return "EDGE_FRAGILE_TO_COSTS"


def render_costs_md(payload: dict) -> str:
    ts = payload["timestamp_audit"]
    lines = [
        "# Costs, Execution & Timestamp Look-Ahead Audit",
        "",
        f"## Judgment: `{payload['judgment']}`",
        "",
        f"Sample: `{payload['sample']['t0']}` → `{payload['sample']['t1']}`",
        "",
        "## Timestamp audit (Sunday BTC candle vs Mon 08:00 ET)",
        "",
        f"- Weeks: `{ts.get('n_weeks')}`",
        f"- Sunday UTC candle complete before Mon 08:00 ET: **`{100*ts.get('pct_sunday_complete_before_mon8et',0):.1f}%`**",
        f"- Monday UTC bar complete before Mon 08:00 ET: **`{100*ts.get('pct_monday_bar_complete_before_mon8et',0):.1f}%`** (must be ~0%)",
        f"- Safe-asof == Sunday proxy: `{100*ts.get('pct_safe_equals_sunday_proxy',0):.1f}%`",
        f"- Median hours Sunday close → Mon 08:00 ET: `{ts.get('median_hours_sunday_close_before_mon8et'):.1f}h`",
        f"- Look-ahead judgment: **`{ts.get('look_ahead_judgment')}`**",
        "",
        "Interpretation: Bitfinex Sunday 00:00–Monday 00:00 UTC candle finishes ~12–13h "
        "before US equity open / QC 08:00 ET decision. Using that bar is **not** look-ahead. "
        "Using the Monday UTC daily bar at Mon 08:00 ET **would** be look-ahead.",
        "",
        "## Holidays / week-start mapping",
        "",
        f"- Week-starts: `{payload['holiday_week_starts']['n_week_starts']}`",
        f"- % Monday: `{100*payload['holiday_week_starts']['pct_monday']:.1f}%`",
        f"- Non-Monday week-starts (holidays): `{payload['holiday_week_starts']['n_non_monday_week_starts']}` "
        f"e.g. `{payload['holiday_week_starts']['non_monday_examples']}`",
        "",
        "## Dividend / SHY–QQQ total return",
        "",
        f"- SHY CAGR Adj−Close: `{payload['total_return_vs_price']['SHY_cagr_adj_minus_close_pp']:.2f}` pp",
        f"- QQQ CAGR Adj−Close: `{payload['total_return_vs_price']['QQQ_cagr_adj_minus_close_pp']:.2f}` pp",
        "- Strategy research path should use **Adj Close (total return)** for both legs.",
        "",
        "## Cost sweep (QC week-start Bitfinex, next-open proxy)",
        "",
        f"Half-spread assumptions: `{payload['assumptions']['half_spread_bps']}` (not NBBO).",
        "",
        "| One-way bps | +half-spreads | Eff RT bps | Switches | Sharpe | CAGR | Vol | MaxDD |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in payload["cost_sweep"]:
        lines.append(
            f"| {r['one_way_bps']} | {r['include_half_spreads']} | {r['effective_rt_bps']:.1f} | "
            f"{r['n_switches']} | {r['sharpe']:.3f} | {100*r['cagr']:.2f}% | "
            f"{100*r['ann_vol']:.2f}% | {100*r['max_dd']:.2f}% |"
        )
    b = payload["baseline_adj_c2c_0bps"]
    lines += [
        "",
        f"Baseline Adj C2C 0bps Sharpe `{b['sharpe']:.3f}` (not open-fill).",
        "",
        "## Tradability notes (SHY)",
        "",
        "- SHY is highly liquid short-Treasury ETF; 1–2 bps half-spread assumption is conservative for size.",
        "- Main friction is **switch count × (commission + spread + open slippage)**, not SHY borrow.",
        "- 0 bps is not admissible for live claims; quote ≥5 bps one-way (+spreads) as stress.",
        "",
    ]
    return "\n".join(lines)


def write_costs_report(config: ProjectConfig, payload: dict) -> Path:
    import shutil

    import yaml

    md = render_costs_md(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.reports_dir / "runs" / f"{stamp}_costs_timestamps"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "costs_payload.json").write_text(json.dumps(payload, indent=2, default=str))
    (run_dir / "costs_execution_timestamps.md").write_text(md)
    with (run_dir / "config_snapshot.yaml").open("w") as f:
        yaml.safe_dump(config.raw, f, sort_keys=False)
    latest = config.reports_dir / "costs_execution_timestamps.md"
    shutil.copy2(run_dir / "costs_execution_timestamps.md", latest)
    return latest
