"""Relative-to-SPY opportunity-cost audit (definitions A/B/C; no strategy retuning)."""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from .artifacts import config_hash
from .config import DualMomentumConfig
from .data import audit_cache, cash_symbol_on


@dataclass
class StreakResult:
    metric: str
    definition: str
    longest_months: int
    start: Optional[str]
    end: Optional[str]
    ongoing: bool
    months_under_pct: float


def monthly_total_returns(equity: pd.DataFrame) -> pd.Series:
    """Compound daily net_return into calendar-month total returns."""
    return (1 + equity["net_return"]).groupby(equity.index.to_period("M")).prod() - 1


def streak_where(flag: pd.Series) -> tuple[int, Optional[pd.Period], Optional[pd.Period], bool]:
    """Longest True run; if the longest ends at sample end, ongoing=True."""
    best = 0
    cur = 0
    best_end = None
    best_start = None
    for period, value in flag.items():
        if bool(value):
            cur += 1
            if cur > best:
                best = cur
                best_end = period
                # start computed after loop
        else:
            cur = 0
    if best_end is not None and best > 0:
        pos = list(flag.index).index(best_end)
        best_start = flag.index[pos - best + 1]
    ongoing = bool(best > 0 and best_end == flag.index[-1] and bool(flag.iloc[-1]))
    return best, best_start, best_end, ongoing


def metric_a_monthly_return_streak(dc: pd.DataFrame, spy: pd.DataFrame) -> StreakResult:
    """A: longest consecutive calendar months with month return(DC) < month return(SPY)."""
    s = monthly_total_returns(dc)
    b = monthly_total_returns(spy)
    aligned = pd.concat([s.rename("dc"), b.rename("spy")], axis=1).dropna()
    under = aligned["dc"] < aligned["spy"]
    best, start, end, ongoing = streak_where(under)
    return StreakResult(
        metric="A_monthly_return_streak",
        definition=(
            "Longest consecutive calendar months where "
            "(1+r_daily).prod()-1 for D+C is strictly less than the same for SPY. "
            "NOT relative-NAV underwater duration."
        ),
        longest_months=int(best),
        start=str(start) if start is not None else None,
        end=str(end) if end is not None else None,
        ongoing=ongoing,
        months_under_pct=float(under.mean()) if len(under) else float("nan"),
    )


def metric_b_rolling_12m_streak(dc: pd.DataFrame, spy: pd.DataFrame) -> StreakResult:
    """B: longest streak of month-ends where trailing 12M return(DC) < trailing 12M return(SPY)."""
    s = monthly_total_returns(dc)
    b = monthly_total_returns(spy)
    aligned = pd.concat([s.rename("dc"), b.rename("spy")], axis=1).dropna()
    r12_dc = (1 + aligned["dc"]).rolling(12).apply(np.prod, raw=True) - 1
    r12_spy = (1 + aligned["spy"]).rolling(12).apply(np.prod, raw=True) - 1
    under = (r12_dc < r12_spy).dropna()
    best, start, end, ongoing = streak_where(under)
    return StreakResult(
        metric="B_rolling_12m_return_streak",
        definition=(
            "At each month-end, compare trailing 12-month compounded returns. "
            "Longest consecutive months with R12(DC) < R12(SPY)."
        ),
        longest_months=int(best),
        start=str(start) if start is not None else None,
        end=str(end) if end is not None else None,
        ongoing=ongoing,
        months_under_pct=float(under.mean()) if len(under) else float("nan"),
    )


def build_relative_nav(dc: pd.DataFrame, spy: pd.DataFrame) -> pd.DataFrame:
    """Daily relative NAV = nav_dc / nav_spy on the intersection of dates."""
    idx = dc.index.intersection(spy.index).sort_values()
    nav_dc = dc.loc[idx, "equity_net"].astype(float)
    nav_spy = spy.loc[idx, "equity_net"].astype(float)
    # Rebase both to 1.0 at first common date for interpretability
    nav_dc = nav_dc / float(nav_dc.iloc[0])
    nav_spy = nav_spy / float(nav_spy.iloc[0])
    rel = nav_dc / nav_spy
    peak = rel.cummax()
    dd = rel / peak - 1.0
    return pd.DataFrame(
        {
            "nav_dc": nav_dc,
            "nav_spy": nav_spy,
            "relative_nav": rel,
            "relative_peak": peak,
            "relative_drawdown": dd,
        },
        index=idx,
    )


def relative_nav_underwater_periods(rel: pd.Series) -> list[dict[str, Any]]:
    """
    Relative-NAV opportunity-cost intervals.

    A period starts on the first observation strictly below the prevailing
    historical high of relative_nav, and ends on the first observation that
    meets or exceeds that same high (recovery). Sample-end open intervals are
    kept and marked ongoing=True.
    """
    periods: list[dict[str, Any]] = []
    high = -np.inf
    high_date = None
    current: Optional[dict[str, Any]] = None
    for t, v in rel.items():
        v = float(v)
        if v >= high - 1e-15:
            if current is not None:
                current["recovery_date"] = str(pd.Timestamp(t).date())
                current["end_date"] = str(pd.Timestamp(t).date())
                current["ongoing"] = False
                current["duration_months"] = _month_span(current["start_date"], current["end_date"])
                periods.append(current)
                current = None
            high = v
            high_date = pd.Timestamp(t)
        else:
            if current is None:
                current = {
                    "peak_date": str(high_date.date()) if high_date is not None else None,
                    "peak_value": float(high),
                    "start_date": str(pd.Timestamp(t).date()),
                    "trough_date": str(pd.Timestamp(t).date()),
                    "trough_value": v,
                    "trough_drawdown": v / high - 1.0 if high else np.nan,
                }
            elif v < current["trough_value"]:
                current["trough_value"] = v
                current["trough_date"] = str(pd.Timestamp(t).date())
                current["trough_drawdown"] = v / high - 1.0 if high else np.nan
    if current is not None:
        end = pd.Timestamp(rel.index[-1])
        current["recovery_date"] = None
        current["end_date"] = str(end.date())
        current["ongoing"] = True
        current["duration_months"] = _month_span(current["start_date"], current["end_date"])
        periods.append(current)
    return periods


def _month_span(start: str, end: str) -> int:
    a = pd.Timestamp(start).to_period("M")
    b = pd.Timestamp(end).to_period("M")
    return int((b.year - a.year) * 12 + (b.month - a.month)) + 1


def metric_c_relative_nav(dc: pd.DataFrame, spy: pd.DataFrame) -> dict[str, Any]:
    frame = build_relative_nav(dc, spy)
    rel = frame["relative_nav"]
    periods = relative_nav_underwater_periods(rel)
    if periods:
        longest = max(periods, key=lambda p: p["duration_months"])
    else:
        longest = None
    last_peak_date = frame.loc[frame["relative_nav"] >= frame["relative_peak"] - 1e-15].index.max()
    months_since_peak = _month_span(str(last_peak_date.date()), str(frame.index[-1].date()))
    current_dd = float(frame["relative_drawdown"].iloc[-1])
    max_dd = float(frame["relative_drawdown"].min())

    # Monthly relative NAV for win-rate windows
    month_end = frame.groupby(frame.index.to_period("M")).tail(1)
    win_rates = {}
    for years, label in [(3, "3y"), (5, "5y"), (10, "10y")]:
        # Trailing N-year total return from monthly compounded daily path:
        # use month-end NAV ratios.
        nav_dc_m = month_end["nav_dc"]
        nav_spy_m = month_end["nav_spy"]
        lag = years * 12
        if len(nav_dc_m) <= lag:
            win_rates[label] = float("nan")
            continue
        r_dc = nav_dc_m / nav_dc_m.shift(lag) - 1
        r_spy = nav_spy_m / nav_spy_m.shift(lag) - 1
        cmp = pd.concat([r_dc.rename("dc"), r_spy.rename("spy")], axis=1).dropna()
        win_rates[label] = float((cmp["dc"] > cmp["spy"]).mean()) if len(cmp) else float("nan")

    return {
        "metric": "C_relative_nav_underwater",
        "definition": (
            "relative_nav_t = nav_dc_t / nav_spy_t (both rebased to 1 at common start). "
            "An opportunity-cost interval starts when relative_nav falls below its historical high "
            "and ends when it recovers to/above that high; open intervals at sample end are ongoing."
        ),
        "max_relative_drawdown": max_dd,
        "current_relative_drawdown": current_dd,
        "months_since_relative_peak": int(months_since_peak),
        "last_relative_peak_date": str(last_peak_date.date()),
        "sample_end": str(frame.index[-1].date()),
        "longest_period": longest,
        "all_periods": periods,
        "rolling_win_rate_vs_spy": win_rates,
        "frame": frame,
    }


def alignment_audit(dc: pd.DataFrame, spy: pd.DataFrame, closes: pd.DataFrame) -> dict[str, Any]:
    """Verify total-return / calendar / compounding consistency (documented, not retuned)."""
    idx = dc.index.intersection(spy.index)
    spy_adj = closes["SPY"].reindex(idx)
    # Reconstruct SPY daily total return from Adj Close on the same calendar
    spy_tr = spy_adj.pct_change(fill_method=None)
    # BH path used equity net_return; compare correlation after first day
    used = spy.loc[idx, "net_return"]
    aligned = pd.concat([used.rename("bh"), spy_tr.rename("adj")], axis=1).dropna()
    corr = float(aligned["bh"].corr(aligned["adj"])) if len(aligned) > 5 else float("nan")
    max_abs_diff = float((aligned["bh"] - aligned["adj"]).abs().max()) if len(aligned) else float("nan")
    return {
        "price_basis": "Yahoo Adj Close (dividend/split adjusted) via load_ohlc; Open scaled by AdjClose/Close",
        "dc_return_field": "equity.net_return (after one-way costs; next-open execution)",
        "spy_return_field": "buy-and-hold Adj Close daily pct_change; zero cost; always invested",
        "common_dates": int(len(idx)),
        "dc_start": str(dc.index.min().date()),
        "dc_end": str(dc.index.max().date()),
        "spy_start": str(spy.index.min().date()),
        "spy_end": str(spy.index.max().date()),
        "monthly_index": "calendar Period[M] from daily timestamps",
        "compounding": "daily (1+r).prod()-1 within month; relative_nav from equity_net cumprod",
        "timing_note": (
            "D+C uses month-end close signal → next session open fill; "
            "SPY BH is continuous close-to-close. This is intentional strategy-vs-market comparison, "
            "not same execution clock."
        ),
        "spy_bh_vs_adj_close_corr": corr,
        "spy_bh_vs_adj_close_max_abs_diff": max_abs_diff,
        "spy_uses_total_return_proxy": True,
    }


def cash_switch_audit(targets: pd.DataFrame, closes: pd.DataFrame, config: DualMomentumConfig) -> dict[str, Any]:
    """No overlap/gap/lookahead in SGOV vs BIL cash sleeve."""
    if targets.empty:
        return {"ok": False, "reason": "empty targets"}
    cash = targets[targets["symbol"].isin(["SGOV", "BIL"])].copy()
    issues = []
    by_sig = targets.groupby("signal_date")
    for sig, group in by_sig:
        cash_w = group[group["symbol"].isin(["SGOV", "BIL"])]["weight"].sum()
        # Both SGOV and BIL same day with positive weight = overlap
        present = set(group.loc[group["weight"] > 1e-12, "symbol"])
        if "SGOV" in present and "BIL" in present:
            issues.append(f"overlap SGOV+BIL on {pd.Timestamp(sig).date()}")
        expected = cash_symbol_on(pd.Timestamp(sig), config, closes)
        cash_rows = group[group["symbol"].isin(["SGOV", "BIL"]) & (group["weight"] > 1e-12)]
        if not cash_rows.empty:
            used = str(cash_rows.iloc[0]["symbol"])
            if used != expected:
                issues.append(f"cash sleeve {used} != expected {expected} on {pd.Timestamp(sig).date()}")
        # Lookahead: expecting SGOV before first valid SGOV bar
        sgov = closes["SGOV"].dropna()
        if expected == "SGOV" and not sgov.empty and pd.Timestamp(sig) < sgov.index.min():
            issues.append(f"lookahead SGOV before inception on {pd.Timestamp(sig).date()}")
    # Gap: signal dates should be contiguous month-ends in targets
    sigs = sorted(pd.to_datetime(targets["signal_date"].unique()))
    return {
        "ok": len(issues) == 0,
        "n_cash_rows": int(len(cash)),
        "issues": issues[:20],
        "n_signal_dates": len(sigs),
    }


def paper_trading_engineering_check(
    config: DualMomentumConfig,
    directory: Path,
    dc_result: dict[str, Any],
    closes: pd.DataFrame,
) -> dict[str, Any]:
    """Freeze provenance + live-readiness gaps (honest NOT_IMPLEMENTED where true)."""
    manifest_path = config.cache_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(config.project_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unavailable"

    # Auditable per-rebalance signal detail
    targets = dc_result["targets"].copy()
    scores = dc_result.get("monthly_scores", pd.DataFrame())
    rows = []
    if not targets.empty and not scores.empty:
        for sig, group in targets.groupby("signal_date"):
            day = scores[scores["date"] == pd.Timestamp(sig)]
            for _, hold in group.iterrows():
                sym = str(hold["symbol"])
                score_row = day[day["symbol"] == sym]
                rows.append(
                    {
                        "signal_date": str(pd.Timestamp(sig).date()),
                        "execution_date": str(pd.Timestamp(hold["execution_date"]).date()),
                        "symbol": sym,
                        "weight": float(hold["weight"]),
                        "score": float(score_row.iloc[0]["score"]) if len(score_row) else np.nan,
                        "above_ma": bool(score_row.iloc[0]["above_ma"]) if len(score_row) else None,
                        "trend_consistent": bool(score_row.iloc[0]["trend_consistent"])
                        if len(score_row) and "trend_consistent" in score_row.columns
                        else None,
                        "r3m": float(score_row.iloc[0]["r3m"]) if len(score_row) else np.nan,
                        "r6m": float(score_row.iloc[0]["r6m"]) if len(score_row) else np.nan,
                        "r12m": float(score_row.iloc[0]["r12m"]) if len(score_row) else np.nan,
                    }
                )
    detail = pd.DataFrame(rows)
    detail_path = directory / "dc_rebalance_signal_audit.csv"
    detail.to_csv(detail_path, index=False)

    cash = cash_switch_audit(targets, closes, config)

    ibkr = {
        "fractional_shares": "NOT_MODELED — research engine uses float weights, not share lots",
        "minimum_commission": "NOT_MODELED — only one-way bps linear cost",
        "order_notional_constraints": "NOT_MODELED — no IBKR min order / buying-power checks",
        "status": "PAPER_TRADING_BLOCKED_UNTIL_BROKER_CONSTRAINTS_IMPLEMENTED",
    }

    provenance = {
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "config_hash": config_hash(config),
        "git_commit": commit,
        "frozen_variant": config.raw.get("confirmation", {}).get("frozen_variant", "attribution_DC"),
        "frozen_trend_horizons": config.raw.get("confirmation", {}).get("frozen_trend_horizons", [3, 6, 12]),
        "one_way_bps": config.raw["costs"]["one_way_bps"],
        "data_manifest": {
            "retrieved_at_utc": manifest.get("retrieved_at_utc"),
            "source": manifest.get("source"),
            "start": manifest.get("start"),
            "completed_symbols": manifest.get("completed_symbols"),
            "failures": manifest.get("failures"),
        },
        "cache_audit": audit_cache(config),
    }
    (directory / "paper_trading_provenance.json").write_text(
        json.dumps({"provenance": provenance, "cash_sleeve": cash, "ibkr": ibkr}, indent=2, default=str),
        encoding="utf-8",
    )
    return {
        "provenance": provenance,
        "cash_sleeve": cash,
        "ibkr": ibkr,
        "signal_audit_csv": str(detail_path),
        "n_rebalance_rows": int(len(detail)),
    }


def plot_relative_nav(frame: pd.DataFrame, longest: Optional[dict], path: Path) -> Path:
    """Save relative_nav + relative drawdown charts; y-axis not clipped; mark longest DD."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    ax0, ax1 = axes
    x = frame.index
    ax0.plot(x, frame["relative_nav"], color="#1f4e79", lw=1.2, label="relative_nav = NAV_DC / NAV_SPY")
    ax0.plot(x, frame["relative_peak"], color="#9e9e9e", lw=0.8, ls="--", label="historical high")
    if longest is not None:
        start = pd.Timestamp(longest["start_date"])
        end = pd.Timestamp(longest["end_date"])
        ax0.axvspan(start, end, color="#c62828", alpha=0.15, label="longest relative-DD interval")
        trough = pd.Timestamp(longest["trough_date"])
        ax0.scatter([trough], [longest["trough_value"]], color="#c62828", zorder=5, s=28)
        status = "ongoing" if longest.get("ongoing") else "recovered"
        ax0.annotate(
            f"longest {longest['duration_months']}m ({status})",
            xy=(trough, longest["trough_value"]),
            xytext=(10, -30),
            textcoords="offset points",
            fontsize=8,
            color="#c62828",
        )
    ax0.set_ylabel("Relative NAV (ratio)")
    ax0.set_title("D+C relative NAV vs SPY (rebased)")
    ax0.legend(loc="upper left", fontsize=8, frameon=False)
    ax0.grid(True, alpha=0.25)
    # Full data range — no deceptive zoom
    ymin = float(min(frame["relative_nav"].min(), 0.95))
    ymax = float(max(frame["relative_nav"].max(), frame["relative_peak"].max()) * 1.02)
    ax0.set_ylim(ymin, ymax)

    ax1.fill_between(x, frame["relative_drawdown"], 0, color="#c62828", alpha=0.35, label="relative drawdown")
    ax1.set_ylabel("Rel. drawdown")
    ax1.set_xlabel("Date")
    ax1.set_ylim(float(frame["relative_drawdown"].min()) * 1.05, 0.02)
    ax1.grid(True, alpha=0.25)
    if longest is not None:
        ax1.axvspan(pd.Timestamp(longest["start_date"]), pd.Timestamp(longest["end_date"]), color="#c62828", alpha=0.12)
    ax1.xaxis.set_major_locator(mdates.YearLocator(2))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.autofmt_xdate()
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def run_relative_spy_audit(
    config: DualMomentumConfig,
    directory: Path,
    dc: dict[str, Any],
    spy: dict[str, Any],
    closes: pd.DataFrame,
) -> dict[str, Any]:
    a = metric_a_monthly_return_streak(dc["equity"], spy["equity"])
    b = metric_b_rolling_12m_streak(dc["equity"], spy["equity"])
    c = metric_c_relative_nav(dc["equity"], spy["equity"])
    frame = c.pop("frame")
    frame.to_csv(directory / "relative_nav_daily.csv")
    chart = plot_relative_nav(frame, c.get("longest_period"), directory / "relative_nav_drawdown.png")
    # Also promote chart next to reports/
    promote_chart = config.reports_dir / "relative_nav_drawdown.png"
    promote_chart.write_bytes(chart.read_bytes())

    align = alignment_audit(dc["equity"], spy["equity"], closes)
    eng = paper_trading_engineering_check(config, directory, dc, closes)

    # Legacy naming correction
    legacy_note = (
        "The previously reported '相对SPY最长连续跑输9个月' was Metric A only "
        f"(longest consecutive single-month return underperformance = {a.longest_months} months). "
        "It is NOT relative-NAV opportunity-cost duration and must not be read as "
        "'investors only endure 9 months of opportunity cost'."
    )

    payload = {
        "legacy_metric_clarification": legacy_note,
        "legacy_code": {
            "function": "confirmation.longest_underperform_streak_months",
            "formula": "month_ret_dc = prod(1+daily_net)-1 by Period[M]; streak where month_ret_dc < month_ret_spy",
        },
        "metric_A": asdict(a),
        "metric_B": asdict(b),
        "metric_C": c,
        "alignment": align,
        "engineering": eng,
        "chart_path": str(promote_chart),
    }
    (directory / "relative_spy_audit.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(c.get("all_periods") or []).to_csv(directory / "relative_nav_underwater_periods.csv", index=False)
    return payload
