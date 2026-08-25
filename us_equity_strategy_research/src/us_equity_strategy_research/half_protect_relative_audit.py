"""Benchmark-relative audit of frozen half_protect (no rule changes).

Uses dual_momentum_etf Metric C (relative NAV = nav_a/nav_b) as the formal
relative underwater definition. Diagnoses prior rel_8020_underwater_days=4382
as a non-Metric-C arithmetic-excess approximation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from dual_momentum_etf.relative_spy_audit import (
    build_relative_nav,
    metric_c_relative_nav,
)

from .analytics import legacy_arithmetic_excess_relative_path
from .artifacts import new_run_directory
from .config import load_config
from .data.prices import load_adj_panels
from .etf_trend_sleeves import _run_weight_schedule, fetch_missing_etfs
from .spy_qqq_protect_audit import (
    COMMON_START,
    ONE_WAY_BPS,
    PRIMARY_SMA,
    build_protect_targets,
    load_dc_and_sleeves,
)

CUTOFFS = ["2015-12-31", "2018-12-31", "2020-12-31", "2022-12-31", "2024-12-31", "latest"]
EXCLUDE_YEARS = [1, 2, 3]


def _to_eq(returns: pd.Series) -> pd.DataFrame:
    r = returns.astype(float).fillna(0.0)
    return pd.DataFrame({"net_return": r, "equity_net": (1.0 + r).cumprod()})


def _perf(returns: pd.Series) -> dict:
    r = returns.dropna()
    if r.empty:
        return {"cagr": np.nan, "sharpe": np.nan, "max_drawdown": np.nan, "end_nav": np.nan}
    eq = (1 + r).cumprod()
    years = max((r.index.max() - r.index.min()).days / 365.25, 1 / 12)
    cagr = float(eq.iloc[-1] ** (1 / years) - 1)
    sharpe = (
        float(r.mean() / r.std(ddof=1) * np.sqrt(252))
        if len(r) > 1 and r.std(ddof=1)
        else np.nan
    )
    max_dd = float((eq / eq.cummax() - 1).min())
    return {"cagr": cagr, "sharpe": sharpe, "max_drawdown": max_dd, "end_nav": float(eq.iloc[-1])}


def _metric_c_pack(strat: pd.Series, bench: pd.Series, label: str) -> dict:
    """Formal Metric C relative NAV pack + trading-day underwater length."""
    c = metric_c_relative_nav(_to_eq(strat), _to_eq(bench))
    frame = c["frame"]
    rel = frame["relative_nav"]
    under = frame["relative_drawdown"] < -1e-15
    longest_td = cur = 0
    for flag in under:
        cur = cur + 1 if flag else 0
        longest_td = max(longest_td, cur)
    ahead = rel[rel > 1.0 + 1e-12]
    first_above_start = str(ahead.index[0].date()) if len(ahead) else None
    cross_up = []
    prev = float(rel.iloc[0])
    for t, v in rel.items():
        v = float(v)
        if prev <= 1.0 + 1e-12 and v > 1.0 + 1e-12:
            cross_up.append(str(pd.Timestamp(t).date()))
        prev = v
    years = max((rel.index.max() - rel.index.min()).days / 365.25, 1 / 12)
    final_rel = float(rel.iloc[-1])
    rel_cagr = float(final_rel ** (1 / years) - 1)
    return {
        "benchmark": label,
        "common_start": str(frame.index[0].date()),
        "common_end": str(frame.index[-1].date()),
        "n_trading_days": int(len(frame)),
        "n_calendar_days": int((frame.index.max() - frame.index.min()).days),
        "final_relative_wealth": final_rel,
        "relative_cagr": rel_cagr,
        "max_relative_underwater": float(c["max_relative_drawdown"]),
        "longest_relative_underwater_trading_days": int(longest_td),
        "longest_relative_underwater_months_metric_c": (
            c["longest_period"]["duration_months"] if c["longest_period"] else 0
        ),
        "longest_period": c["longest_period"],
        "currently_underwater": bool(c["current_relative_drawdown"] < -1e-15),
        "current_distance_from_relative_peak": float(c["current_relative_drawdown"]),
        "last_relative_peak_date": c["last_relative_peak_date"],
        "months_since_relative_peak": c["months_since_relative_peak"],
        "frac_days_relative_wealth_gt_1": float((rel > 1.0).mean()),
        "first_date_relative_wealth_gt_1": first_above_start,
        "last_date_relative_wealth_gt_1": str(ahead.index[-1].date()) if len(ahead) else None,
        "cross_above_1_dates": cross_up[:10],
        "n_cross_above_1": len(cross_up),
        "definition": c["definition"],
    }


def _legacy_diag(strat: pd.Series, bench: pd.Series) -> dict:
    """Reproduce prior audit metric for diagnosis (NOT Metric C)."""
    return legacy_arithmetic_excess_relative_path(strat, bench)


def _rolling_vs(half: pd.Series, bench: pd.Series, *, years: int, step: int = 63) -> dict:
    idx = half.index.intersection(bench.index).sort_values()
    span = years * 252
    rows = []
    for st in idx[::step]:
        pos = idx.get_indexer([st])[0]
        en_pos = pos + span
        if en_pos >= len(idx):
            continue
        en = idx[en_pos]
        w = idx[(idx >= st) & (idx <= en)]
        if len(w) < span * 0.9:
            continue
        h = _perf(half.reindex(w))
        b = _perf(bench.reindex(w))
        rows.append(
            {
                "cagr_win": bool(h["cagr"] > b["cagr"]),
                "sharpe_win": bool(h["sharpe"] > b["sharpe"]),
                "maxdd_win": bool(h["max_drawdown"] > b["max_drawdown"]),
            }
        )
    if not rows:
        return {"n": 0}
    df = pd.DataFrame(rows)
    return {
        "n": int(len(df)),
        "cagr_win_rate": float(df["cagr_win"].mean()),
        "sharpe_win_rate": float(df["sharpe_win"].mean()),
        "maxdd_win_rate": float(df["maxdd_win"].mean()),
        "triple_win_rate": float((df["cagr_win"] & df["sharpe_win"] & df["maxdd_win"]).mean()),
    }


def _cutoff_table(half: pd.Series, b80: pd.Series, b60: pd.Series, start: pd.Timestamp) -> list[dict]:
    out = []
    for label in CUTOFFS:
        end = half.index.max() if label == "latest" else pd.Timestamp(label)
        idx = half.index[(half.index >= start) & (half.index <= end)]
        if len(idx) < 20:
            continue
        h = half.reindex(idx)
        x80 = b80.reindex(idx)
        x60 = b60.reindex(idx)
        ph, p80, p60 = _perf(h), _perf(x80), _perf(x60)
        rel80 = build_relative_nav(_to_eq(h), _to_eq(x80))["relative_nav"].iloc[-1]
        rel60 = build_relative_nav(_to_eq(h), _to_eq(x60))["relative_nav"].iloc[-1]
        out.append(
            {
                "cutoff": label if label == "latest" else str(end.date()),
                "start": str(idx.min().date()),
                "end": str(idx.max().date()),
                "half_cagr": ph["cagr"],
                "half_sharpe": ph["sharpe"],
                "half_maxdd": ph["max_drawdown"],
                "m80_cagr": p80["cagr"],
                "m80_sharpe": p80["sharpe"],
                "m80_maxdd": p80["max_drawdown"],
                "m60_cagr": p60["cagr"],
                "m60_sharpe": p60["sharpe"],
                "m60_maxdd": p60["max_drawdown"],
                "final_rel_vs_80": float(rel80),
                "final_rel_vs_60": float(rel60),
                "cagr_gt_80": bool(ph["cagr"] > p80["cagr"]),
                "cagr_gt_60": bool(ph["cagr"] > p60["cagr"]),
                "sharpe_gt_60": bool(ph["sharpe"] > p60["sharpe"]),
                "maxdd_better_60": bool(ph["max_drawdown"] > p60["max_drawdown"]),
            }
        )
    return out


def _exclude_recent(half: pd.Series, b80: pd.Series, b60: pd.Series, years: int) -> dict:
    cut = half.index.max() - pd.Timedelta(days=365 * years)
    idx = half.index[half.index <= cut]
    h, x80, x60 = half.reindex(idx), b80.reindex(idx), b60.reindex(idx)
    ph, p80, p60 = _perf(h), _perf(x80), _perf(x60)
    rel80 = float(build_relative_nav(_to_eq(h), _to_eq(x80))["relative_nav"].iloc[-1])
    rel60 = float(build_relative_nav(_to_eq(h), _to_eq(x60))["relative_nav"].iloc[-1])
    return {
        "exclude_last_years": years,
        "end": str(idx.max().date()),
        "half": ph,
        "frozen_80_20": p80,
        "frozen_60_40": p60,
        "final_rel_vs_80": rel80,
        "final_rel_vs_60": rel60,
        "cagr_edge_vs_80": ph["cagr"] - p80["cagr"],
        "cagr_edge_vs_60": ph["cagr"] - p60["cagr"],
    }


def _annual_relative(half: pd.Series, bench: pd.Series, label: str) -> dict:
    h = (1 + half).resample("YE").prod() - 1
    b = (1 + bench).resample("YE").prod() - 1
    aligned = pd.concat([h.rename("half"), b.rename("bench")], axis=1).dropna()
    diff = aligned["half"] - aligned["bench"]
    years = [str(i.year) for i in diff.index]
    pairs = {y: float(v) for y, v in zip(years, diff.values)}
    rel = build_relative_nav(_to_eq(half), _to_eq(bench))["relative_nav"]
    full_growth = float(rel.iloc[-1] / rel.iloc[0] - 1)
    contrib = {}
    for n in (1, 2, 3, 5):
        end = rel.index.max()
        start_n = end - pd.DateOffset(years=n)
        sub = rel[rel.index >= start_n]
        if len(sub) < 2:
            contrib[f"last_{n}y_share_of_log_rel_growth"] = np.nan
            continue
        full_log = np.log(float(rel.iloc[-1])) - np.log(float(rel.iloc[0]))
        recent_log = np.log(float(sub.iloc[-1])) - np.log(float(sub.iloc[0]))
        if abs(full_log) > 1e-12:
            contrib[f"last_{n}y_share_of_log_rel_growth"] = float(recent_log / full_log)
        else:
            contrib[f"last_{n}y_share_of_log_rel_growth"] = np.nan
    best_y = max(pairs, key=pairs.get) if pairs else None
    worst_y = min(pairs, key=pairs.get) if pairs else None
    return {
        "benchmark": label,
        "annual_excess": pairs,
        "positive_year_frac": float((diff > 0).mean()) if len(diff) else np.nan,
        "best_year": best_y,
        "best_year_excess": pairs.get(best_y) if best_y else np.nan,
        "worst_year": worst_y,
        "worst_year_excess": pairs.get(worst_y) if worst_y else np.nan,
        "full_relative_wealth_growth": full_growth,
        **contrib,
    }


def _decide(cutoffs: list[dict], rolling60: dict, exclude: dict, metric_error: bool) -> dict:
    early = [r for r in cutoffs if r["end"] <= "2022-12-31"]
    late = [r for r in cutoffs if r["end"] > "2022-12-31"]
    early_cagr = all(r["cagr_gt_60"] for r in early) if early else False
    late_only = (
        (not any(r["cagr_gt_60"] for r in early)) and all(r["cagr_gt_60"] for r in late)
        if late
        else False
    )
    roll_ok = rolling60.get("cagr_win_rate", 0) >= 0.55 and rolling60.get("sharpe_win_rate", 0) >= 0.50
    ex3 = exclude.get(3, {})
    edge_full = cutoffs[-1]["half_cagr"] - cutoffs[-1]["m60_cagr"] if cutoffs else np.nan
    edge_ex3 = ex3.get("cagr_edge_vs_60", np.nan)
    depends_recent = bool(pd.notna(edge_full) and edge_full > 0 and pd.notna(edge_ex3) and edge_ex3 < 0)

    if metric_error:
        label = "C"
        reason = (
            "Prior rel_8020_underwater_days=4382 used non-Metric-C arithmetic excess cumprod "
            "(final approx wealth <1) instead of formal relative NAV ratio (final wealth >1). "
            "Metric fixed; strategy rules unchanged."
        )
    elif late_only or depends_recent:
        label = "B"
        reason = "half only exceeds 60/40 at recent cutoffs and/or relative edge depends on last years."
    elif early_cagr and roll_ok and not depends_recent:
        label = "A"
        reason = (
            "half vs 60/40 CAGR advantage appears across fixed cutoffs from common start "
            "and rolling windows are supportive; eligible as independent DEFENSIVE_SHADOW sim "
            "(does not replace 60/40)."
        )
    else:
        label = "B"
        reason = (
            f"vs-60/40 not stably dominant (early_cagr_all={early_cagr}, roll_ok={roll_ok}, "
            f"depends_on_recent={depends_recent}); keep RESEARCH_ONLY."
        )

    return {
        "choice": label,
        "reason": reason,
        "evidence": {
            "early_cutoffs_cagr_gt_60_all": early_cagr,
            "late_only_cagr_gt_60": late_only,
            "rolling_60_ok": roll_ok,
            "rolling_60": rolling60,
            "depends_on_recent_3y": depends_recent,
            "edge_full_vs_60": edge_full,
            "edge_exclude_3y_vs_60": edge_ex3,
            "metric_error_detected": metric_error,
        },
    }


def run_half_protect_relative_audit(project_root: Optional[Path] = None) -> Path:
    config = load_config(project_root)
    fetch_missing_etfs(config.cache_dir)
    opens, closes, _ = load_adj_panels(
        config.cache_dir, ["SPY", "QQQ", "BIL", "VTI"], subdir="etf"
    )
    bil_start = closes["BIL"].dropna().index.min()
    start = max(COMMON_START, bil_start)
    opens = opens.loc[opens.index >= start]
    closes = closes.loc[closes.index >= start]

    targets = build_protect_targets(closes, mode="half_protect", sma_months=PRIMARY_SMA)
    half_out = _run_weight_schedule(opens, closes, targets, one_way_bps=ONE_WAY_BPS)
    sleeves = load_dc_and_sleeves(ONE_WAY_BPS)

    half_r = half_out["equity"]["net_return"]
    r80 = sleeves["eq80"]["net_return"]
    r60 = sleeves["eq60"]["net_return"]
    spy_r = closes["SPY"].pct_change(fill_method=None)

    common = (
        half_r.index.intersection(r80.index).intersection(r60.index).intersection(spy_r.dropna().index)
    ).sort_values()
    half_r = half_r.reindex(common).fillna(0.0)
    r80 = r80.reindex(common).fillna(0.0)
    r60 = r60.reindex(common).fillna(0.0)
    spy_r = spy_r.reindex(common).fillna(0.0)

    books = {
        "half_protect": _perf(half_r),
        "frozen_80_20_spy_dc": _perf(r80),
        "frozen_60_40_spy_dc": _perf(r60),
        "spy_bh": _perf(spy_r),
    }

    pack80 = _metric_c_pack(half_r, r80, "frozen_80_20_spy_dc")
    pack60 = _metric_c_pack(half_r, r60, "frozen_60_40_spy_dc")
    pack_spy = _metric_c_pack(half_r, spy_r, "spy_bh")
    legacy80 = _legacy_diag(half_r, r80)

    metric_error = bool(
        abs(legacy80["final_approx_relative"] - pack80["final_relative_wealth"]) > 0.02
        or (legacy80["final_approx_relative"] < 1.0 and pack80["final_relative_wealth"] > 1.0)
    )
    # legacy key alias used in alignment block
    legacy80 = {
        **legacy80,
        "relative_underwater_days_approx": legacy80.get(
            "relative_underwater_trading_sessions_approx"
        ),
    }

    alignment = {
        "half_start": str(half_r.index.min().date()),
        "half_end": str(half_r.index.max().date()),
        "n_common_trading_days": int(len(common)),
        "n_calendar_days_span": int((common.max() - common.min()).days),
        "all_rebased_to_1_at_common_start": True,
        "metric_c_definition": pack80["definition"],
        "prior_4382_unit": "trading_days under legacy excess method",
        "prior_4382_equals_almost_full_sample": bool(
            abs(legacy80["relative_underwater_days_approx"] - (len(common) - 1)) < 200
        ),
        "nan_check_half": int(half_r.isna().sum()),
        "nan_check_80": int(r80.isna().sum()),
        "nan_check_60": int(r60.isna().sum()),
        "legacy_vs_metric_c": {
            "legacy_final_rel": legacy80["final_approx_relative"],
            "metric_c_final_rel": pack80["final_relative_wealth"],
            "discrepancy": float(pack80["final_relative_wealth"] - legacy80["final_approx_relative"]),
        },
    }

    rolling = {
        "half_vs_80_3y": _rolling_vs(half_r, r80, years=3),
        "half_vs_80_5y": _rolling_vs(half_r, r80, years=5),
        "half_vs_60_3y": _rolling_vs(half_r, r60, years=3),
        "half_vs_60_5y": _rolling_vs(half_r, r60, years=5),
    }
    cutoffs = _cutoff_table(half_r, r80, r60, common.min())
    exclude = {y: _exclude_recent(half_r, r80, r60, y) for y in EXCLUDE_YEARS}
    annual80 = _annual_relative(half_r, r80, "80_20")
    annual60 = _annual_relative(half_r, r60, "60_40")
    decision = _decide(cutoffs, rolling["half_vs_60_3y"], exclude, metric_error=metric_error)

    run_dir = new_run_directory(
        config,
        "half_protect_relative_audit",
        {"experiment": "half_protect_metric_c_relative_v1"},
    )
    payload = {
        "alignment": alignment,
        "legacy_diag_vs_80": legacy80,
        "books": books,
        "metric_c_vs_80": pack80,
        "metric_c_vs_60": pack60,
        "metric_c_vs_spy": pack_spy,
        "rolling": rolling,
        "cutoffs": cutoffs,
        "exclude_recent": exclude,
        "annual_vs_80": annual80,
        "annual_vs_60": annual60,
        "decision": decision,
        "constraints": {
            "no_rule_change": True,
            "no_exit_ratio_search": True,
            "no_weight_change": True,
            "no_sma_retune": True,
            "no_ibkr_change": True,
            "paper_default_remains": "80% SPY + 20% D+C",
        },
    }
    (run_dir / "relative_audit.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    build_relative_nav(_to_eq(half_r), _to_eq(r80)).to_csv(run_dir / "rel_nav_vs_80.csv")
    build_relative_nav(_to_eq(half_r), _to_eq(r60)).to_csv(run_dir / "rel_nav_vs_60.csv")

    report = _write_report(config.reports_dir / "half_protect_relative_audit.md", payload, run_dir)
    (run_dir / "half_protect_relative_audit.md").write_text(
        report.read_text(encoding="utf-8"), encoding="utf-8"
    )

    prior = config.reports_dir / "spy_qqq_protect_half_audit.md"
    if prior.exists():
        text = prior.read_text(encoding="utf-8")
        note = (
            "\n\n## Erratum — relative underwater days\n\n"
            "Prior `rel_8020_underwater_days=4382` used `(1+r_s-r_b).cumprod()` (not Metric C). "
            "That approximation ended **below** 1 while true `nav_half/nav_80` ends **above** 1. "
            "See `reports/half_protect_relative_audit.md` for the corrected Metric C audit.\n"
        )
        if "Erratum — relative underwater days" not in text:
            prior.write_text(text.rstrip() + note, encoding="utf-8")

    status = config.reports_dir / "PROJECT_STATUS.md"
    if status.exists():
        prev = status.read_text(encoding="utf-8")
        add = (
            "\n## half_protect relative (Metric C) audit\n\n"
            f"- Report: `reports/half_protect_relative_audit.md`\n"
            f"- Decision: **{decision['choice']}** — {decision['reason'][:160]}\n"
            "- Paper default unchanged: **80% SPY + 20% D+C**; no further half_protect tuning; "
            "no Sharadar; no IBKR change\n"
        )
        if "half_protect relative (Metric C) audit" not in prev:
            status.write_text(prev.rstrip() + "\n" + add, encoding="utf-8")
    return report


def _fmt(x, pct=False):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "n/a"
    if pct:
        return f"{100 * float(x):.2f}%"
    return f"{float(x):.4f}"


def _write_report(path: Path, payload: dict, run_dir: Path) -> Path:
    d = payload["decision"]
    a = payload["alignment"]
    p80 = payload["metric_c_vs_80"]
    p60 = payload["metric_c_vs_60"]
    leg = payload["legacy_diag_vs_80"]
    books = payload["books"]
    lines = [
        "# half_protect — Final Benchmark-Relative Audit (Metric C)",
        "",
        "## Decision (A / B / C)",
        "",
        f"**Choice: `{d['choice']}`**",
        "",
        d["reason"],
        "",
        "- Default paper candidate unchanged: **80% SPY + 20% D+C**",
        "- No further half_protect parameter / exit-ratio tuning",
        "- Do not purchase Sharadar for this line; do not modify IBKR config",
        "",
        "## Why 4382 appeared while CAGR was higher",
        "",
        "1. Prior `rel_8020_underwater_days` did **not** use formal Metric C "
        "(`relative_nav = nav_half / nav_80`, both rebased to 1 at common start).",
        "2. It used `relative_to_benchmark` → `(1 + r_half - r_80).cumprod()`, an arithmetic-excess path.",
        f"3. That approx ended at `{_fmt(leg['final_approx_relative'])}` (<1), while Metric C ends at "
        f"`{_fmt(p80['final_relative_wealth'])}` (>1).",
        f"4. The `4382` count is **trading days** (daily-index loop), almost the full sample "
        f"(`n_trading_days={a['n_common_trading_days']}`, calendar span `{a['n_calendar_days_span']}` days).",
        "5. Under **Metric C**, half's wealth is above 80/20 on nearly all days "
        f"(`frac_days_rel>1 = {_fmt(p80['frac_days_relative_wealth_gt_1'], True)}`), "
        "but opportunity-cost underwater vs its **2009 relative peak** lasts "
        f"`{p80['longest_relative_underwater_months_metric_c']}` months (ongoing) — "
        "same style as the D+C sleeve Metric C reports.",
        "",
        "### Alignment checks",
        "",
        f"- Common start/end: `{p80['common_start']}` → `{p80['common_end']}`",
        f"- Both NAVs rebased to 1.0 at common start: `{a['all_rebased_to_1_at_common_start']}`",
        f"- NaN counts half/80/60: `{a['nan_check_half']}` / `{a['nan_check_80']}` / `{a['nan_check_60']}`",
        f"- Legacy final rel vs Metric C: `{_fmt(a['legacy_vs_metric_c']['legacy_final_rel'])}` vs "
        f"`{_fmt(a['legacy_vs_metric_c']['metric_c_final_rel'])}` "
        f"(gap `{_fmt(a['legacy_vs_metric_c']['discrepancy'])}`)",
        f"- First date Metric C rel>1: `{p80['first_date_relative_wealth_gt_1']}`; "
        f"last: `{p80['last_date_relative_wealth_gt_1']}`",
        f"- Cross-above-1 events (sample): `{p80['cross_above_1_dates']}` (n=`{p80['n_cross_above_1']}`)",
        f"- Currently underwater vs relative peak (80/20): `{p80['currently_underwater']}` "
        f"at `{_fmt(p80['current_distance_from_relative_peak'], True)}` "
        f"(peak `{p80['last_relative_peak_date']}`)",
        f"- Run: `{run_dir}`",
        "",
        "## Absolute levels (common sample)",
        "",
        "| name | CAGR | Sharpe | MaxDD | end NAV |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in ["half_protect", "frozen_80_20_spy_dc", "frozen_60_40_spy_dc", "spy_bh"]:
        b = books[name]
        lines.append(
            f"| {name} | {_fmt(b['cagr'], True)} | {_fmt(b['sharpe'])} | "
            f"{_fmt(b['max_drawdown'], True)} | {_fmt(b['end_nav'])} |"
        )

    lines.extend(
        [
            "",
            "## 1. Metric C relative packs",
            "",
            "| vs | final rel wealth | rel CAGR | max rel UW | longest UW trading days | "
            "longest UW months (C) | still UW? | dist to rel peak |",
            "|---|---:|---:|---:|---:|---:|---|---:|",
        ]
    )
    for pack in (p80, p60, payload["metric_c_vs_spy"]):
        lines.append(
            f"| {pack['benchmark']} | {_fmt(pack['final_relative_wealth'])} | "
            f"{_fmt(pack['relative_cagr'], True)} | {_fmt(pack['max_relative_underwater'], True)} | "
            f"{pack['longest_relative_underwater_trading_days']} | "
            f"{pack['longest_relative_underwater_months_metric_c']} | {pack['currently_underwater']} | "
            f"{_fmt(pack['current_distance_from_relative_peak'], True)} |"
        )

    lines.extend(["", "## 2. Rolling 3y / 5y win rates (half vs benchmarks)", ""])
    for key, title in [
        ("half_vs_80_3y", "half vs 80/20 — 3y"),
        ("half_vs_80_5y", "half vs 80/20 — 5y"),
        ("half_vs_60_3y", "half vs 60/40 — 3y"),
        ("half_vs_60_5y", "half vs 60/40 — 5y"),
    ]:
        r = payload["rolling"][key]
        lines.append(
            f"- **{title}** (n={r.get('n')}): CAGR win `{_fmt(r.get('cagr_win_rate'), True)}`, "
            f"Sharpe win `{_fmt(r.get('sharpe_win_rate'), True)}`, "
            f"MaxDD win `{_fmt(r.get('maxdd_win_rate'), True)}`, "
            f"triple `{_fmt(r.get('triple_win_rate'), True)}`"
        )

    lines.extend(
        [
            "",
            "## 3. Fixed cutoffs (always from common start)",
            "",
            "| cutoff | half CAGR/Sharpe/MaxDD | 80/20 | 60/40 | final rel vs80 | final rel vs60 |",
            "|---|---|---|---|---:|---:|",
        ]
    )
    for row in payload["cutoffs"]:
        lines.append(
            f"| {row['cutoff']} | {_fmt(row['half_cagr'], True)} / {_fmt(row['half_sharpe'])} / "
            f"{_fmt(row['half_maxdd'], True)} | "
            f"{_fmt(row['m80_cagr'], True)} / {_fmt(row['m80_sharpe'])} / {_fmt(row['m80_maxdd'], True)} | "
            f"{_fmt(row['m60_cagr'], True)} / {_fmt(row['m60_sharpe'])} / {_fmt(row['m60_maxdd'], True)} | "
            f"{_fmt(row['final_rel_vs_80'])} | {_fmt(row['final_rel_vs_60'])} |"
        )

    lines.extend(["", "## 4. Exclude last 1 / 2 / 3 years (all three recomputed)", ""])
    for y in EXCLUDE_YEARS:
        ex = payload["exclude_recent"][y]
        lines.append(
            f"- **Exclude last {y}y** (end `{ex['end']}`): "
            f"half `{_fmt(ex['half']['cagr'], True)}` / `{_fmt(ex['half']['sharpe'])}` / "
            f"`{_fmt(ex['half']['max_drawdown'], True)}`; "
            f"80/20 `{_fmt(ex['frozen_80_20']['cagr'], True)}`; "
            f"60/40 `{_fmt(ex['frozen_60_40']['cagr'], True)}`; "
            f"CAGR edge vs80 `{_fmt(ex['cagr_edge_vs_80'], True)}`, "
            f"vs60 `{_fmt(ex['cagr_edge_vs_60'], True)}`; "
            f"final rel vs80 `{_fmt(ex['final_rel_vs_80'])}`, vs60 `{_fmt(ex['final_rel_vs_60'])}`"
        )

    a80, a60 = payload["annual_vs_80"], payload["annual_vs_60"]
    lines.extend(
        [
            "",
            "## 5. Annual relative returns",
            "",
            f"- vs 80/20: positive years `{_fmt(a80['positive_year_frac'], True)}`; "
            f"best `{a80['best_year']}` (`{_fmt(a80['best_year_excess'], True)}`); "
            f"worst `{a80['worst_year']}` (`{_fmt(a80['worst_year_excess'], True)}`); "
            f"last 3y share of log-rel growth `{_fmt(a80.get('last_3y_share_of_log_rel_growth'), True)}`",
            f"- vs 60/40: positive years `{_fmt(a60['positive_year_frac'], True)}`; "
            f"best `{a60['best_year']}` (`{_fmt(a60['best_year_excess'], True)}`); "
            f"worst `{a60['worst_year']}` (`{_fmt(a60['worst_year_excess'], True)}`); "
            f"last 3y share of log-rel growth `{_fmt(a60.get('last_3y_share_of_log_rel_growth'), True)}`",
            "",
            "### Annual excess table (half − bench)",
            "",
            "| year | vs 80/20 | vs 60/40 |",
            "|---:|---:|---:|",
        ]
    )
    years = sorted(set(a80["annual_excess"]) | set(a60["annual_excess"]))
    for y in years:
        lines.append(
            f"| {y} | {_fmt(a80['annual_excess'].get(y), True)} | "
            f"{_fmt(a60['annual_excess'].get(y), True)} |"
        )

    lines.extend(["", "## Disposition after Metric C fix", ""])
    ev = d["evidence"]
    if d["choice"] == "C":
        if ev.get("early_cutoffs_cagr_gt_60_all") and ev.get("rolling_60_ok") and not ev.get(
            "depends_on_recent_3y"
        ):
            lines.append(
                "- After correcting Metric C: evidence supports treating half as an **independent "
                "DEFENSIVE_SHADOW research track** (does **not** replace frozen 60/40); wait for forward evidence."
            )
        elif ev.get("late_only_cagr_gt_60") or ev.get("depends_on_recent_3y"):
            lines.append(
                "- After correcting Metric C: vs-60/40 edge looks **recent-dependent** → keep "
                "**RESEARCH_ONLY**, do not add a second paper shadow book."
            )
        else:
            lines.append(
                "- After correcting Metric C: vs-60/40 stability is mixed → keep **RESEARCH_ONLY** "
                "for paper books; Metric C report is the corrected record."
            )
    elif d["choice"] == "A":
        lines.append(
            "- Recommend half enter independent **DEFENSIVE_SHADOW** simulation alongside "
            "(not replacing) 60/40; wait for forward evidence."
        )
    else:
        lines.append("- Keep half as **RESEARCH_ONLY**; do not enter paper simulation.")

    lines.extend(
        [
            "",
            "- **80/20** remains the default paper / IBKR candidate.",
            "- Do **not** retune half_protect; do **not** buy Sharadar; do **not** auto-change IBKR.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
