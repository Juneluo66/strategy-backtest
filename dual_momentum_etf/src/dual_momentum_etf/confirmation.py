"""Final confirmation validation for frozen D+C (no further combo search)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from .attribution import (
    align_start,
    holding_weight_stats,
    relative_stats,
    run_buy_and_hold,
    run_sixty_forty,
    trim_result,
    window_total_return,
    worst_trailing_return,
)
from .backtest import run_variant
from .config import DualMomentumConfig
from .metrics import _stats
from .relative_spy_audit import run_relative_spy_audit
from .signals import build_monthly_signal_panel, month_end_index, next_trading_day


def _max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return np.nan
    equity = (1 + returns).cumprod()
    return float((equity / equity.cummax() - 1).min())


def rolling_window_compare(
    dc: pd.DataFrame,
    ref: pd.DataFrame,
    *,
    window_days: int = 252 * 3,
    step_days: int = 21,
) -> pd.DataFrame:
    """Rolling 3y windows: return gap, drawdown improvement, Sharpe dominance."""
    idx = dc.index.intersection(ref.index).sort_values()
    dc_r = dc.loc[idx, "net_return"]
    ref_r = ref.loc[idx, "net_return"]
    rows = []
    if len(idx) < window_days:
        return pd.DataFrame(rows)
    for end_i in range(window_days - 1, len(idx), step_days):
        start_i = end_i - window_days + 1
        sl = idx[start_i : end_i + 1]
        a = dc_r.loc[sl]
        b = ref_r.loc[sl]
        a_stats = _stats(a)
        b_stats = _stats(b)
        a_dd = _max_drawdown(a)
        b_dd = _max_drawdown(b)
        rows.append(
            {
                "end": sl[-1],
                "start": sl[0],
                "dc_cagr": a_stats["cagr"],
                "a_cagr": b_stats["cagr"],
                "cagr_gap_dc_minus_a": a_stats["cagr"] - b_stats["cagr"],
                "dc_sharpe": a_stats["sharpe"],
                "a_sharpe": b_stats["sharpe"],
                "dc_sharpe_better": bool(a_stats["sharpe"] > b_stats["sharpe"])
                if pd.notna(a_stats["sharpe"]) and pd.notna(b_stats["sharpe"])
                else False,
                "dc_dd": a_dd,
                "a_dd": b_dd,
                # Improvement: DC drawdown less severe (e.g. -0.15 > -0.25)
                "dc_dd_better": bool(a_dd > b_dd) if pd.notna(a_dd) and pd.notna(b_dd) else False,
            }
        )
    return pd.DataFrame(rows)


def longest_underperform_streak_months(strategy: pd.DataFrame, spy: pd.DataFrame) -> dict[str, Any]:
    """Longest consecutive calendar months where strategy return < SPY return."""
    s = (1 + strategy["net_return"]).groupby(strategy.index.to_period("M")).prod() - 1
    b = (1 + spy["net_return"]).groupby(spy.index.to_period("M")).prod() - 1
    aligned = pd.concat([s.rename("s"), b.rename("b")], axis=1).dropna()
    under = aligned["s"] < aligned["b"]
    best = 0
    cur = 0
    best_end = None
    for period, flag in under.items():
        if flag:
            cur += 1
            if cur > best:
                best = cur
                best_end = period
        else:
            cur = 0
    best_start = None
    if best_end is not None and best > 0:
        # walk back
        pos = list(under.index).index(best_end)
        best_start = under.index[pos - best + 1]
    return {
        "longest_underperform_months_vs_spy": int(best),
        "streak_start": str(best_start) if best_start is not None else None,
        "streak_end": str(best_end) if best_end is not None else None,
        "months_underperform_pct": float(under.mean()) if len(under) else np.nan,
    }


def category_weights(targets: pd.DataFrame, category_map: dict[str, str]) -> dict[str, float]:
    if targets is None or targets.empty:
        return {}
    frame = targets.copy()
    frame["category"] = frame["symbol"].map(
        lambda s: "cash" if s in {"SGOV", "BIL"} else category_map.get(s, "other")
    )
    by = frame.groupby(["signal_date", "category"])["weight"].sum().unstack(fill_value=0.0)
    return {col: float(by[col].mean()) for col in by.columns}


def pit_audit(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    config: DualMomentumConfig,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Confirm month-end signal / next-open execution and no pre-inception trading."""
    common = opens.index.intersection(closes.index).sort_values()
    month_ends = set(month_end_index(common))
    targets = result["targets"]
    checks = {
        "all_signal_dates_are_month_ends": True,
        "all_execution_after_signal": True,
        "no_pre_inception_risk_weights": True,
        "cash_proxy_before_sgov": True,
    }
    details: list[str] = []
    if targets.empty:
        return {"ok": False, "checks": checks, "details": ["empty targets"]}

    for _, row in targets.iterrows():
        sig = pd.Timestamp(row["signal_date"])
        exe = pd.Timestamp(row["execution_date"])
        if sig not in month_ends:
            checks["all_signal_dates_are_month_ends"] = False
            details.append(f"non-month-end signal {sig.date()}")
        if not (exe > sig):
            checks["all_execution_after_signal"] = False
            details.append(f"execution not after signal {sig.date()}->{exe.date()}")
        # next trading day exactly
        nxt = next_trading_day(common, sig)
        if nxt is not None and exe != nxt:
            checks["all_execution_after_signal"] = False
            details.append(f"execution not next session {sig.date()} expected {nxt.date()} got {exe.date()}")

        symbol = str(row["symbol"])
        weight = float(row["weight"])
        if weight <= 1e-12:
            continue
        if symbol in {"SGOV", "BIL"}:
            continue
        hist = closes[symbol].loc[:sig].dropna() if symbol in closes.columns else pd.Series(dtype=float)
        if hist.empty:
            checks["no_pre_inception_risk_weights"] = False
            details.append(f"{symbol} weighted before any price at {sig.date()}")
        else:
            # Require enough history for 12m return roughly (>= 12 month-ends or 200 trading days)
            if len(hist) < 200:
                # Still allow if score panel had the name — flag soft
                details.append(f"soft: {symbol} thin history ({len(hist)} bars) at {sig.date()}")

    # SGOV inception: before first SGOV bar, cash sleeve should be BIL when present
    sgov = closes["SGOV"].dropna() if "SGOV" in closes.columns else pd.Series(dtype=float)
    sgov_start = sgov.index.min() if not sgov.empty else None
    cash_rows = targets[targets["symbol"].isin(["SGOV", "BIL"])]
    if sgov_start is not None and not cash_rows.empty:
        early = cash_rows[cash_rows["signal_date"] < sgov_start]
        if not early.empty and (early["symbol"] == "SGOV").any():
            checks["cash_proxy_before_sgov"] = False
            details.append("SGOV used before inception")
        late = cash_rows[cash_rows["signal_date"] >= sgov_start]
        # After inception prefer SGOV; BIL only if SGOV missing — soft check
        if not late.empty and (late["symbol"] == "BIL").all():
            details.append("soft: never switched to SGOV after inception")

    # Signal panel uses only <= date: recompute one month and compare score
    panel = result.get("monthly_scores", pd.DataFrame())
    score_ok = True
    if not panel.empty:
        sample_date = pd.Timestamp(panel["date"].max())
        day = panel[panel["date"] == sample_date]
        me = closes.loc[:sample_date]
        # R12 for SPY if present
        if "SPY" in day["symbol"].values:
            spy_row = day[day["symbol"] == "SPY"].iloc[0]
            month_ends_idx = month_end_index(me.index)
            if len(month_ends_idx) >= 13:
                me_close = closes["SPY"].reindex(month_ends_idx).dropna()
                if len(me_close) >= 13:
                    expected = float(me_close.iloc[-1] / me_close.iloc[-13] - 1)
                    if pd.notna(spy_row["r12m"]) and abs(float(spy_row["r12m"]) - expected) > 1e-9:
                        score_ok = False
                        details.append("r12m mismatch vs recomputed month-end series")
    checks["month_end_returns_reproducible"] = score_ok

    # Pre-inception: symbols with NaN close on signal date must not appear as risk holdings
    for _, row in targets.iterrows():
        sig = pd.Timestamp(row["signal_date"])
        symbol = str(row["symbol"])
        if symbol in {"SGOV", "BIL"} or float(row["weight"]) <= 0:
            continue
        if symbol not in closes.columns:
            checks["no_pre_inception_risk_weights"] = False
            details.append(f"{symbol} missing column on signal {sig.date()}")
            continue
        if sig not in closes.index or pd.isna(closes.loc[sig, symbol]):
            checks["no_pre_inception_risk_weights"] = False
            details.append(f"{symbol} missing close on signal {sig.date()}")

    ok = all(checks.values())
    return {
        "ok": ok,
        "checks": checks,
        "details": details[:30],
        "sgov_inception": str(sgov_start.date()) if sgov_start is not None else None,
    }


def evaluate_gates(payload: dict[str, Any]) -> dict[str, Any]:
    """Pass criteria — D+C need not beat A on every metric."""
    full = payload["full_sample"]
    oos = payload["oos"]
    roll = payload["rolling"]
    crisis = payload["crisis_dependence"]
    costs = payload["cost_sensitivity"]
    neigh = payload["neighborhood"]
    pit = payload["pit_audit"]

    cagr_gap = full["dc"]["cagr"] - full["a"]["cagr"]
    gates = {
        "cagr_only_mildly_lags_A": bool(cagr_gap > -0.025),  # within 2.5pp
        "majority_windows_lower_dd": bool(roll["dd_better_pct"] >= 0.50),
        "oos_not_clearly_broken": bool(
            pd.notna(oos["dc"]["sharpe"])
            and oos["dc"]["sharpe"] > 0
            and (oos["dc"]["cagr"] - oos["a"]["cagr"]) > -0.05
        ),
        "not_only_2008": bool(crisis["ex_2008_dd_better_or_cagr_close"]),
        "cost_stable": bool(costs["stable"]),
        "neighborhood_stable": bool(neigh["stable"]),
        "pit_ok": bool(pit["ok"]),
    }
    gates["PASS"] = all(gates.values())
    gates["notes"] = {
        "cagr_gap_dc_minus_a": cagr_gap,
        "dd_better_pct": roll["dd_better_pct"],
        "sharpe_better_pct": roll["sharpe_better_pct"],
        "mean_cagr_gap_roll": roll["mean_cagr_gap"],
    }
    return gates


def run_confirmation(config: DualMomentumConfig, opens: pd.DataFrame, closes: pd.DataFrame) -> dict[str, Any]:
    conf = config.raw.get("confirmation", {})
    dc_name = conf.get("frozen_variant", "attribution_DC")
    a_name = conf.get("reference_a", "attribution_A")
    simple_name = conf.get("simple_dual", "simple_dual_mom")
    oos_bounds = tuple(config.raw["research_windows"]["locked_oos"])
    gfc = tuple(config.raw.get("stress_windows", {}).get("gfc_2008", ["2007-10-01", "2009-03-31"]))
    cost_grid = list(conf.get("cost_bps", [5.0, 10.0, 20.0]))
    neighborhoods = [tuple(x) for x in conf.get("trend_neighborhoods", [[3, 6, 12], [2, 6, 12], [3, 5, 12], [3, 6, 11], [4, 6, 12]])]
    base_horizons = tuple(conf.get("frozen_trend_horizons", [3, 6, 12]))

    # Core runs at frozen 5bp
    dc = run_variant(opens, closes, config, dc_name, trend_horizons=base_horizons)
    a = run_variant(opens, closes, config, a_name, trend_horizons=base_horizons)
    simple = run_variant(opens, closes, config, simple_name, trend_horizons=base_horizons)
    start = align_start({"dc": dc, "a": a, "simple": simple})
    dc, a, simple = trim_result(dc, start), trim_result(a, start), trim_result(simple, start)
    sixty = trim_result(run_sixty_forty(opens, closes, config, start=start), start)
    spy = trim_result(run_buy_and_hold(closes, "SPY", start=start, name="bh_spy"), start)

    def pack_stats(eq: pd.DataFrame) -> dict[str, float]:
        s = _stats(eq["net_return"])
        return {
            "cagr": s["cagr"],
            "sharpe": s["sharpe"],
            "volatility": s["volatility"],
            "max_drawdown": s["max_drawdown"],
            "worst_12m": worst_trailing_return(eq, 252),
        }

    full_sample = {
        "dc": pack_stats(dc["equity"]),
        "a": pack_stats(a["equity"]),
        "sixty_forty": pack_stats(sixty["equity"]),
        "simple_dual_mom": pack_stats(simple["equity"]),
        "spy": pack_stats(spy["equity"]),
    }

    def window_pack(eq: pd.DataFrame, start_s: str, end_s: str) -> dict[str, float]:
        sl = eq.loc[start_s:end_s]
        return pack_stats(sl) if not sl.empty else pack_stats(pd.DataFrame({"net_return": pd.Series(dtype=float)}))

    oos = {
        "bounds": list(oos_bounds),
        "dc": window_pack(dc["equity"], oos_bounds[0], oos_bounds[1]),
        "a": window_pack(a["equity"], oos_bounds[0], oos_bounds[1]),
        "sixty_forty": window_pack(sixty["equity"], oos_bounds[0], oos_bounds[1]),
        "simple_dual_mom": window_pack(simple["equity"], oos_bounds[0], oos_bounds[1]),
        "spy": window_pack(spy["equity"], oos_bounds[0], oos_bounds[1]),
        "total_return": {
            "dc": window_total_return(dc["equity"], oos_bounds[0], oos_bounds[1]),
            "a": window_total_return(a["equity"], oos_bounds[0], oos_bounds[1]),
            "sixty_forty": window_total_return(sixty["equity"], oos_bounds[0], oos_bounds[1]),
            "simple_dual_mom": window_total_return(simple["equity"], oos_bounds[0], oos_bounds[1]),
        },
    }

    roll_df = rolling_window_compare(dc["equity"], a["equity"])
    rolling = {
        "n_windows": int(len(roll_df)),
        "mean_cagr_gap": float(roll_df["cagr_gap_dc_minus_a"].mean()) if len(roll_df) else np.nan,
        "median_cagr_gap": float(roll_df["cagr_gap_dc_minus_a"].median()) if len(roll_df) else np.nan,
        "dd_better_pct": float(roll_df["dc_dd_better"].mean()) if len(roll_df) else np.nan,
        "sharpe_better_pct": float(roll_df["dc_sharpe_better"].mean()) if len(roll_df) else np.nan,
        "positive_cagr_gap_pct": float((roll_df["cagr_gap_dc_minus_a"] > 0).mean()) if len(roll_df) else np.nan,
    }

    # Exclude GFC window from equity by masking returns to 0? Better: concatenate pre+post
    def exclude_window(eq: pd.DataFrame, start_s: str, end_s: str) -> pd.DataFrame:
        out = eq.copy()
        mask = (out.index >= start_s) & (out.index <= end_s)
        out.loc[mask, ["gross_return", "net_return", "cost"]] = 0.0
        # Recompute equity path after zeroing crisis days (removes crisis contribution)
        out["equity_net"] = (1 + out["net_return"]).cumprod()
        out["equity_gross"] = (1 + out["gross_return"]).cumprod()
        return out

    dc_x = exclude_window(dc["equity"], gfc[0], gfc[1])
    a_x = exclude_window(a["equity"], gfc[0], gfc[1])
    roll_x = rolling_window_compare(dc_x, a_x)
    full_x_dc = pack_stats(dc_x)
    full_x_a = pack_stats(a_x)
    crisis_dependence = {
        "gfc_window": list(gfc),
        "gfc_total_return": {
            "dc": window_total_return(dc["equity"], gfc[0], gfc[1]),
            "a": window_total_return(a["equity"], gfc[0], gfc[1]),
        },
        "ex_2008_full": {"dc": full_x_dc, "a": full_x_a},
        "ex_2008_cagr_gap": full_x_dc["cagr"] - full_x_a["cagr"],
        "ex_2008_rolling_dd_better_pct": float(roll_x["dc_dd_better"].mean()) if len(roll_x) else np.nan,
        "ex_2008_dd_better_or_cagr_close": bool(
            (float(roll_x["dc_dd_better"].mean()) if len(roll_x) else 0) >= 0.45
            or abs((full_x_dc["cagr"] - full_x_a["cagr"]) - (full_sample["dc"]["cagr"] - full_sample["a"]["cagr"])) < 0.015
        ),
    }

    # Cost sensitivity for DC and A
    cost_rows = []
    for bps in cost_grid:
        dc_c = trim_result(
            run_variant(opens, closes, config, dc_name, one_way_bps=float(bps), trend_horizons=base_horizons),
            start,
        )
        a_c = trim_result(
            run_variant(opens, closes, config, a_name, one_way_bps=float(bps), trend_horizons=base_horizons),
            start,
        )
        ds = pack_stats(dc_c["equity"])
        as_ = pack_stats(a_c["equity"])
        cost_rows.append(
            {
                "bps": bps,
                "dc_cagr": ds["cagr"],
                "dc_sharpe": ds["sharpe"],
                "dc_max_drawdown": ds["max_drawdown"],
                "a_cagr": as_["cagr"],
                "a_sharpe": as_["sharpe"],
                "cagr_gap": ds["cagr"] - as_["cagr"],
                "sharpe_gap": ds["sharpe"] - as_["sharpe"],
            }
        )
    cost_df = pd.DataFrame(cost_rows)
    # Stable if sign of cagr_gap near zero band and sharpe_gap doesn't flip wildly
    base_gap = float(cost_df.loc[cost_df["bps"] == 5.0, "cagr_gap"].iloc[0]) if (cost_df["bps"] == 5).any() else float(cost_df["cagr_gap"].iloc[0])
    cost_stable = bool(
        cost_df["cagr_gap"].max() - cost_df["cagr_gap"].min() < 0.01
        and all(g > -0.03 for g in cost_df["cagr_gap"])
    )
    cost_sensitivity = {"rows": cost_rows, "stable": cost_stable, "base_cagr_gap": base_gap}

    # Neighborhood — report only, do NOT pick max Sharpe
    neigh_rows = []
    for horizons in neighborhoods:
        dc_n = trim_result(
            run_variant(opens, closes, config, dc_name, trend_horizons=horizons),
            start,
        )
        st = pack_stats(dc_n["equity"])
        neigh_rows.append(
            {
                "horizons": f"{horizons[0]}/{horizons[1]}/{horizons[2]}",
                "is_frozen": list(horizons) == list(base_horizons),
                "cagr": st["cagr"],
                "sharpe": st["sharpe"],
                "max_drawdown": st["max_drawdown"],
            }
        )
    neigh_df = pd.DataFrame(neigh_rows)
    frozen_row = neigh_df[neigh_df["is_frozen"]].iloc[0]
    # Stable if all neighbors within 1.5pp CAGR and 0.15 Sharpe of frozen
    neighborhood = {
        "rows": neigh_rows,
        "frozen": f"{base_horizons[0]}/{base_horizons[1]}/{base_horizons[2]}",
        "stable": bool(
            ((neigh_df["cagr"] - frozen_row["cagr"]).abs() < 0.015).all()
            and ((neigh_df["sharpe"] - frozen_row["sharpe"]).abs() < 0.15).all()
        ),
        "note": "Neighborhood is diagnostic only; frozen 3/6/12 is NOT reselected by Sharpe.",
    }

    pit = pit_audit(opens, closes, config, dc)
    holdings = holding_weight_stats(dc["targets"])
    cats = category_weights(dc["targets"], config.category_map())
    # Keep Metric A under a precise name; full A/B/C audit runs below.
    streak = longest_underperform_streak_months(dc["equity"], spy["equity"])
    streak["metric_name"] = "A_monthly_return_streak"
    streak["warning"] = (
        "This is consecutive single-month return underperformance vs SPY, "
        "NOT relative-NAV opportunity-cost duration."
    )

    payload = {
        "frozen_variant": dc_name,
        "common_start": str(start.date()),
        "full_sample": full_sample,
        "oos": oos,
        "rolling": rolling,
        "rolling_windows": roll_df,
        "crisis_dependence": crisis_dependence,
        "cost_sensitivity": cost_sensitivity,
        "neighborhood": neighborhood,
        "pit_audit": pit,
        "holdings": holdings,
        "category_weights": cats,
        "spy_streak": streak,
        "relative": {
            "vs_a": relative_stats(dc["equity"], a["equity"]),
            "vs_sixty_forty": relative_stats(dc["equity"], sixty["equity"]),
            "vs_simple": relative_stats(dc["equity"], simple["equity"]),
            "vs_spy": relative_stats(dc["equity"], spy["equity"]),
        },
        "results": {"dc": dc, "a": a, "simple": simple, "sixty_forty": sixty, "spy": spy},
        "_opens": opens,
        "_closes": closes,
    }
    payload["gates"] = evaluate_gates(payload)
    return payload


def write_confirmation_report(directory: Path, study: dict[str, Any], promote_to: Optional[Path] = None) -> Path:
    def pct(x):
        if x is None or (isinstance(x, float) and x != x):
            return "n/a"
        return f"{x:.2%}"

    def num(x):
        if x is None or (isinstance(x, float) and x != x):
            return "n/a"
        return f"{x:.2f}"

    g = study["gates"]
    full = study["full_sample"]
    oos = study["oos"]
    roll = study["rolling"]
    crisis = study["crisis_dependence"]
    lines = [
        "# D+C Confirmation Validation",
        "",
        f"- Frozen variant: `{study['frozen_variant']}` (category + trend consistency, **no vol-adj**, no hysteresis, no B)",
        f"- Common start: `{study['common_start']}`",
        f"- Verdict: **{'PASS' if g['PASS'] else 'FAIL'}**",
        "",
        "## Gates",
        "",
    ]
    for key, value in g.items():
        if key in {"PASS", "notes"}:
            continue
        lines.append(f"- `{key}`: {'PASS' if value else 'FAIL'}")
    lines.append(f"- notes: `{json.dumps(g['notes'], default=str)}`")

    lines.extend(
        [
            "",
            "## Full sample",
            "",
            "| Strategy | CAGR | Sharpe | MaxDD | Worst12M |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for name in ["dc", "a", "sixty_forty", "simple_dual_mom", "spy"]:
        s = full[name]
        label = {"dc": "D+C", "a": "A", "sixty_forty": "60/40", "simple_dual_mom": "simple_dual", "spy": "SPY"}[name]
        lines.append(
            f"| {label} | {pct(s['cagr'])} | {num(s['sharpe'])} | {pct(s['max_drawdown'])} | {pct(s['worst_12m'])} |"
        )

    lines.extend(
        [
            "",
            f"## Locked OOS `{oos['bounds'][0]}` → `{oos['bounds'][1]}`",
            "",
            "| Strategy | CAGR | Sharpe | MaxDD | Total return |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for name in ["dc", "a", "sixty_forty", "simple_dual_mom", "spy"]:
        s = oos[name]
        tot = oos["total_return"].get(name, np.nan) if name in oos["total_return"] else np.nan
        label = {"dc": "D+C", "a": "A", "sixty_forty": "60/40", "simple_dual_mom": "simple_dual", "spy": "SPY"}[name]
        lines.append(
            f"| {label} | {pct(s['cagr'])} | {num(s['sharpe'])} | {pct(s['max_drawdown'])} | {pct(tot)} |"
        )

    lines.extend(
        [
            "",
            "## Rolling 3Y (D+C vs A)",
            "",
            f"- Windows: {roll['n_windows']}",
            f"- Mean CAGR gap (DC−A): {pct(roll['mean_cagr_gap'])}",
            f"- Median CAGR gap: {pct(roll['median_cagr_gap'])}",
            f"- Share windows DC CAGR > A: {pct(roll['positive_cagr_gap_pct'])}",
            f"- Share windows DC MaxDD better: {pct(roll['dd_better_pct'])}",
            f"- Share windows DC Sharpe better: {pct(roll['sharpe_better_pct'])}",
            "",
            "## Crisis dependence (exclude GFC returns)",
            "",
            f"- GFC total return DC/A: {pct(crisis['gfc_total_return']['dc'])} / {pct(crisis['gfc_total_return']['a'])}",
            f"- Ex-2008 CAGR gap DC−A: {pct(crisis['ex_2008_cagr_gap'])}",
            f"- Ex-2008 rolling DD-better%: {pct(crisis['ex_2008_rolling_dd_better_pct'])}",
            "",
            "## Cost sensitivity (one-way bps)",
            "",
            "| bps | DC CAGR | DC Sharpe | A CAGR | CAGR gap |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for row in study["cost_sensitivity"]["rows"]:
        lines.append(
            f"| {row['bps']:.0f} | {pct(row['dc_cagr'])} | {num(row['dc_sharpe'])} | {pct(row['a_cagr'])} | {pct(row['cagr_gap'])} |"
        )
    lines.append(f"- Cost stability flag: **{'PASS' if study['cost_sensitivity']['stable'] else 'FAIL'}**")

    lines.extend(
        [
            "",
            "## C-horizon neighborhood (diagnostic only; do not re-pick)",
            "",
            f"- Frozen horizons: `{study['neighborhood']['frozen']}`",
            f"- {study['neighborhood']['note']}",
            "",
            "| Horizons | Frozen? | CAGR | Sharpe | MaxDD |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for row in study["neighborhood"]["rows"]:
        lines.append(
            f"| {row['horizons']} | {'yes' if row['is_frozen'] else 'no'} | {pct(row['cagr'])} | {num(row['sharpe'])} | {pct(row['max_drawdown'])} |"
        )
    lines.append(
        f"- Neighborhood stability flag: **{'PASS' if study['neighborhood']['stable'] else 'FAIL'}**"
    )

    pit = study["pit_audit"]
    lines.extend(["", "## PIT / inception audit", "", f"- Overall: **{'PASS' if pit['ok'] else 'FAIL'}**", f"- SGOV inception: `{pit.get('sgov_inception')}`"])
    for k, v in pit["checks"].items():
        lines.append(f"- `{k}`: {'ok' if v else 'FAIL'}")
    if pit["details"]:
        lines.append("- Details:")
        for d in pit["details"][:15]:
            lines.append(f"  - {d}")

    h = study["holdings"]
    from .config import load_config as _load_config

    cfg = _load_config()
    rel_audit = run_relative_spy_audit(
        cfg,
        directory,
        study["results"]["dc"],
        study["results"]["spy"],
        study["_closes"],
    )
    study["relative_spy_audit"] = rel_audit

    lines.extend(
        [
            "",
            "## Holdings / concentration",
            "",
            f"- Avg weight QQQ/SPY/cash: {pct(h['avg_weight_QQQ'])} / {pct(h['avg_weight_SPY'])} / {pct(h['avg_weight_cash'])}",
            f"- Max single risk weight: {pct(h['max_single_weight'])}",
            f"- QQQ held months: {pct(h['qqq_held_pct'])}; cash-only months: {pct(h['cash_only_pct'])}",
            f"- Category avg weights: `{json.dumps(study['category_weights'], default=str)}`",
            "",
            "## Relative-to-SPY audit (do not conflate A/B/C)",
            "",
            "### Legacy clarification",
            "",
            f"- {rel_audit['legacy_metric_clarification']}",
            f"- Prior code: `{rel_audit['legacy_code']['function']}`",
            f"- Formula: `{rel_audit['legacy_code']['formula']}`",
            "",
        ]
    )
    ma, mb, mc = rel_audit["metric_A"], rel_audit["metric_B"], rel_audit["metric_C"]
    longest = mc.get("longest_period") or {}
    lines.extend(
        [
            "### Metric A — longest consecutive **single-month return** below SPY",
            "",
            f"- Definition: {ma['definition']}",
            f"- Longest streak: **{ma['longest_months']} months** ({ma['start']} → {ma['end']})"
            f"{' [ongoing]' if ma['ongoing'] else ''}",
            f"- Share of months under: {pct(ma['months_under_pct'])}",
            "",
            "### Metric B — longest streak of trailing **12-month return** below SPY",
            "",
            f"- Definition: {mb['definition']}",
            f"- Longest streak: **{mb['longest_months']} months** ({mb['start']} → {mb['end']})"
            f"{' [ongoing]' if mb['ongoing'] else ''}",
            f"- Share of months under: {pct(mb['months_under_pct'])}",
            "",
            "### Metric C — **relative NAV** opportunity-cost intervals",
            "",
            f"- Definition: {mc['definition']}",
            f"- Max relative drawdown: **{pct(mc['max_relative_drawdown'])}**",
            f"- Current relative drawdown: **{pct(mc['current_relative_drawdown'])}**",
            f"- Months since last relative-NAV high: **{mc['months_since_relative_peak']}**"
            f" (peak `{mc['last_relative_peak_date']}`, sample end `{mc['sample_end']}`)",
            f"- Rolling win rate vs SPY (DC trailing return > SPY): "
            f"3y={pct(mc['rolling_win_rate_vs_spy'].get('3y'))}, "
            f"5y={pct(mc['rolling_win_rate_vs_spy'].get('5y'))}, "
            f"10y={pct(mc['rolling_win_rate_vs_spy'].get('10y'))}",
        ]
    )
    if longest:
        lines.append(
            f"- Longest relative-NAV underwater: **{longest['duration_months']} months**"
            f" | start `{longest['start_date']}` | trough `{longest['trough_date']}` "
            f"(dd {pct(longest.get('trough_drawdown'))}) | "
            f"recovery `{longest.get('recovery_date') or 'NONE'}` | "
            f"**{'ongoing' if longest.get('ongoing') else 'recovered'}**"
        )
    align = rel_audit["alignment"]
    eng = rel_audit["engineering"]
    lines.extend(
        [
            "",
            f"- Chart: `{rel_audit['chart_path']}`",
            "",
            "### Alignment (D+C vs SPY)",
            "",
            f"- Price basis: {align['price_basis']}",
            f"- D+C field: {align['dc_return_field']}",
            f"- SPY field: {align['spy_return_field']}",
            f"- Timing: {align['timing_note']}",
            f"- SPY BH vs Adj Close daily corr={num(align['spy_bh_vs_adj_close_corr'])}, "
            f"max abs diff={align['spy_bh_vs_adj_close_max_abs_diff']}",
            "",
            "### Paper-trading engineering freeze",
            "",
            f"- config_hash: `{eng['provenance']['config_hash']}`",
            f"- git_commit: `{eng['provenance']['git_commit']}`",
            f"- data retrieved_at: `{eng['provenance']['data_manifest'].get('retrieved_at_utc')}`",
            f"- rebalance signal audit CSV: `{eng['signal_audit_csv']}` ({eng['n_rebalance_rows']} rows)",
            f"- SGOV/BIL sleeve audit: **{'PASS' if eng['cash_sleeve']['ok'] else 'FAIL'}**"
            f" issues={eng['cash_sleeve'].get('issues')}",
            f"- IBKR constraints: `{eng['ibkr']['status']}` "
            f"(fractional/min commission/notional = NOT_MODELED in research engine)",
            "",
            "## Interpretation",
            "",
            "- Pass does **not** require D+C to beat A on CAGR/Sharpe every period.",
            "- Require mild CAGR lag, majority DD improvement, intact OOS, not solely 2008-driven, stable costs/neighborhood, clean PIT.",
            "- Do **not** interpret Metric A (single-month streak) as investor opportunity-cost duration; use Metric C.",
            "",
        ]
    )

    path = directory / "dc_confirmation.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Artifact dumps
    study["rolling_windows"].to_csv(directory / "rolling_3y_dc_vs_a.csv", index=False)
    pd.DataFrame(study["cost_sensitivity"]["rows"]).to_csv(directory / "cost_sensitivity.csv", index=False)
    pd.DataFrame(study["neighborhood"]["rows"]).to_csv(directory / "trend_neighborhood.csv", index=False)
    serializable = {
        k: v
        for k, v in study.items()
        if k not in {"results", "rolling_windows", "_opens", "_closes"}
    }
    (directory / "dc_confirmation.json").write_text(
        json.dumps(serializable, indent=2, default=str), encoding="utf-8"
    )
    for name, payload in study["results"].items():
        payload["equity"].to_csv(directory / f"{name}_equity.csv")
        if not payload["targets"].empty:
            payload["targets"].to_csv(directory / f"{name}_targets.csv", index=False)

    if promote_to is not None:
        promote_to.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        (promote_to.parent / "dc_confirmation.json").write_text(
            json.dumps(serializable, indent=2, default=str), encoding="utf-8"
        )
    return path
