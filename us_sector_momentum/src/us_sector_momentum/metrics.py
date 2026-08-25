"""Performance metrics, Sharpe(rf), and formal Metric C relative wealth."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

METRIC_C_DEFINITION = (
    "relative_nav_t = nav_strategy_t / nav_benchmark_t "
    "(both rebased to 1.0 at the first common date). "
    "Relative underwater = relative_nav / relative_nav.cummax() - 1. "
    "Distance from relative peak = current_relative_drawdown (negative when underwater)."
)


def _month_span(start: pd.Timestamp, end: pd.Timestamp) -> int:
    a = pd.Timestamp(start).to_period("M")
    b = pd.Timestamp(end).to_period("M")
    return int((b.year - a.year) * 12 + (b.month - a.month)) + 1


def _longest_under_streak(under_flags: pd.Series):
    longest = cur = 0
    best_start = best_end = None
    run_start = None
    for t, flag in under_flags.items():
        if bool(flag):
            if cur == 0:
                run_start = pd.Timestamp(t)
            cur += 1
            if cur > longest:
                longest = cur
                best_start = run_start
                best_end = pd.Timestamp(t)
        else:
            cur = 0
            run_start = None
    return longest, best_start, best_end


def build_metric_c_relative_frame(strategy: pd.Series, benchmark: pd.Series) -> pd.DataFrame:
    aligned = pd.concat(
        [strategy.rename("strategy_return"), benchmark.rename("benchmark_return")],
        axis=1,
    ).dropna()
    cols = [
        "strategy_return",
        "benchmark_return",
        "strategy_nav",
        "benchmark_nav",
        "relative_nav",
        "relative_peak",
        "relative_drawdown",
    ]
    if aligned.empty:
        return pd.DataFrame(columns=cols)
    nav_s = (1.0 + aligned["strategy_return"]).cumprod()
    nav_b = (1.0 + aligned["benchmark_return"]).cumprod()
    nav_s = nav_s / float(nav_s.iloc[0])
    nav_b = nav_b / float(nav_b.iloc[0])
    rel = nav_s / nav_b
    peak = rel.cummax()
    return pd.DataFrame(
        {
            "strategy_return": aligned["strategy_return"],
            "benchmark_return": aligned["benchmark_return"],
            "strategy_nav": nav_s,
            "benchmark_nav": nav_b,
            "relative_nav": rel,
            "relative_peak": peak,
            "relative_drawdown": rel / peak - 1.0,
        },
        index=aligned.index,
    )


def metric_c_relative_stats(strategy: pd.Series, benchmark: pd.Series) -> dict:
    frame = build_metric_c_relative_frame(strategy, benchmark)
    empty = {
        "final_relative_nav": np.nan,
        "relative_cagr": np.nan,
        "relative_max_dd": np.nan,
        "relative_underwater_trading_sessions": np.nan,
        "relative_underwater_calendar_days": np.nan,
        "relative_underwater_months": np.nan,
        "current_relative_drawdown": np.nan,
        "distance_from_relative_peak": np.nan,
        "currently_underwater": False,
        "n_common_observations": 0,
        "definition": METRIC_C_DEFINITION,
    }
    if len(frame) < 2:
        return empty
    under = frame["relative_drawdown"] < -1e-15
    longest_td, uw_start, uw_end = _longest_under_streak(under)
    if uw_start is not None and uw_end is not None:
        cal_days = int((uw_end - uw_start).days)
        months = _month_span(uw_start, uw_end)
    else:
        cal_days = 0
        months = 0
    years = max((frame.index.max() - frame.index.min()).days / 365.25, 1 / 12)
    final_rel = float(frame["relative_nav"].iloc[-1])
    rel_cagr = float(final_rel ** (1 / years) - 1) if years > 0 and final_rel > 0 else np.nan
    cur_dd = float(frame["relative_drawdown"].iloc[-1])
    return {
        "final_relative_nav": final_rel,
        "relative_cagr": rel_cagr,
        "relative_max_dd": float(frame["relative_drawdown"].min()),
        "relative_underwater_trading_sessions": float(longest_td),
        "relative_underwater_calendar_days": float(cal_days),
        "relative_underwater_months": float(months),
        "current_relative_drawdown": cur_dd,
        "distance_from_relative_peak": cur_dd,
        "currently_underwater": bool(cur_dd < -1e-15),
        "n_common_observations": int(len(frame)),
        "common_start": str(frame.index[0].date()),
        "common_end": str(frame.index[-1].date()),
        "definition": METRIC_C_DEFINITION,
        "frame": frame,
    }


def _as_returns(series: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    s = series.reindex(index)
    if s.dropna().empty:
        return s
    if s.dropna().abs().median() > 0.05:
        return s.pct_change(fill_method=None).reindex(index)
    return s


def window_return(returns: pd.Series, start: str, end: str) -> float:
    sl = returns.loc[start:end].dropna()
    if sl.empty:
        return float("nan")
    return float((1 + sl).prod() - 1)


def rich_metrics(
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    spy: pd.Series,
    qqq: Optional[pd.Series] = None,
    equal_weight: Optional[pd.Series] = None,
    rf: Optional[pd.Series] = None,
    rf_meta: Optional[dict] = None,
    turnover_status: str = "measured",
    crisis_windows: Optional[dict] = None,
) -> dict:
    net = equity["net_return"].dropna()
    gross = equity["gross_return"].dropna() if "gross_return" in equity else net
    if net.empty:
        return {"status": "EMPTY"}
    years = max((net.index.max() - net.index.min()).days / 365.25, 1 / 12)
    eq = (1 + net).cumprod()
    final_wealth = float(eq.iloc[-1])
    dd = eq / eq.cummax() - 1.0
    max_dd = float(dd.min())
    under = eq < eq.cummax()
    longest = cur = 0
    for flag in under:
        cur = cur + 1 if flag else 0
        longest = max(longest, cur)
    monthly = net.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    yearly = net.resample("YE").apply(lambda x: (1 + x).prod() - 1)
    rolling_12m = (1 + net).rolling(252).apply(lambda x: x.prod() - 1, raw=True)
    vol = float(net.std(ddof=1) * np.sqrt(252)) if len(net) > 1 else np.nan
    cagr = float(eq.iloc[-1] ** (1 / years) - 1)
    downside = net[net < 0]
    sortino = (
        float(net.mean() / downside.std(ddof=1) * np.sqrt(252))
        if len(downside) > 1 and downside.std(ddof=1)
        else np.nan
    )

    sharpe_rf = np.nan
    sharpe_rf0 = (
        float(net.mean() / net.std(ddof=1) * np.sqrt(252))
        if len(net) > 1 and net.std(ddof=1)
        else np.nan
    )
    if rf is not None:
        rf_s = _as_returns(rf, net.index)
        aligned = pd.concat([net.rename("r"), rf_s.rename("rf")], axis=1).dropna()
        if len(aligned) > 5 and aligned["r"].std(ddof=1) > 0:
            excess = aligned["r"] - aligned["rf"]
            if excess.std(ddof=1) > 0:
                sharpe_rf = float(excess.mean() / excess.std(ddof=1) * np.sqrt(252))

    if turnover_status == "measured" and trades is not None and not trades.empty and "turnover" in trades:
        one_way = float(trades["turnover"].sum() / 2)
        ann_turn = one_way / years
        n_trades = int(len(trades))
        cost_total = float(trades["cost"].sum()) if "cost" in trades else float(equity["cost"].sum())
    elif turnover_status == "buy_and_hold":
        one_way = ann_turn = cost_total = 0.0
        n_trades = 0
    else:
        one_way = ann_turn = cost_total = n_trades = np.nan

    gross_nav = (1 + gross).cumprod()
    gross_cagr = float(gross_nav.iloc[-1] ** (1 / years) - 1) if len(gross) else np.nan
    gross_final_wealth = float(gross_nav.iloc[-1]) if len(gross) else np.nan
    cost_drag = gross_cagr - cagr if pd.notna(gross_cagr) else np.nan

    def _beta_block(bench: pd.Series, prefix: str) -> dict:
        b = _as_returns(bench, net.index)
        aligned_b = pd.concat([net, b], axis=1).dropna()
        if len(aligned_b) <= 5:
            return {
                f"corr_{prefix}": np.nan,
                f"beta_{prefix}": np.nan,
                f"up_capture_{prefix}": np.nan,
                f"down_capture_{prefix}": np.nan,
            }
        corr = float(aligned_b.corr().iloc[0, 1])
        cov = float(np.cov(aligned_b.iloc[:, 0], aligned_b.iloc[:, 1])[0, 1])
        var_b = float(np.var(aligned_b.iloc[:, 1], ddof=1))
        beta = cov / var_b if var_b > 0 else np.nan
        up = aligned_b[aligned_b.iloc[:, 1] > 0]
        down = aligned_b[aligned_b.iloc[:, 1] < 0]
        up_cap = (
            float(up.iloc[:, 0].mean() / up.iloc[:, 1].mean())
            if len(up) and up.iloc[:, 1].mean() != 0
            else np.nan
        )
        down_cap = (
            float(down.iloc[:, 0].mean() / down.iloc[:, 1].mean())
            if len(down) and down.iloc[:, 1].mean() != 0
            else np.nan
        )
        return {
            f"corr_{prefix}": corr,
            f"beta_{prefix}": beta,
            f"up_capture_{prefix}": up_cap,
            f"down_capture_{prefix}": down_cap,
        }

    spy_ret = _as_returns(spy, net.index)
    out = {
        "cagr": cagr,
        "final_wealth": final_wealth,
        "gross_cagr": gross_cagr,
        "gross_final_wealth": gross_final_wealth,
        "volatility": vol,
        "sharpe": sharpe_rf if pd.notna(sharpe_rf) else sharpe_rf0,
        "sharpe_rf": sharpe_rf,
        "sharpe_rf0": sharpe_rf0,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "max_dd_duration_trading_sessions": float(longest),
        "calmar": (cagr / abs(max_dd)) if max_dd else np.nan,
        "worst_year": float(yearly.min()) if len(yearly) else np.nan,
        "worst_rolling_12m": float(rolling_12m.min()) if rolling_12m.notna().any() else np.nan,
        "year_win_rate": float((yearly > 0).mean()) if len(yearly) else np.nan,
        "month_win_rate": float((monthly > 0).mean()) if len(monthly) else np.nan,
        "annualized_turnover": ann_turn,
        "avg_trades_per_year": (n_trades / years) if pd.notna(n_trades) else np.nan,
        "cost_drag_cagr": cost_drag,
        "cost_total": cost_total,
        "turnover_status": turnover_status,
        "start": str(net.index.min().date()),
        "end": str(net.index.max().date()),
        "n_days": int(len(net)),
        "rel_definition": METRIC_C_DEFINITION,
        "rf_meta": rf_meta,
    }
    out.update(_beta_block(spy, "spy"))
    out["corr_spy"] = out["corr_spy"]
    out["beta_spy"] = out["beta_spy"]
    out["up_capture"] = out["up_capture_spy"]
    out["down_capture"] = out["down_capture_spy"]

    mc_spy = metric_c_relative_stats(net, spy_ret)
    out.update(
        {
            "rel_spy_final_relative_nav": mc_spy["final_relative_nav"],
            "rel_spy_relative_cagr": mc_spy["relative_cagr"],
            "rel_spy_max_dd": mc_spy["relative_max_dd"],
            "rel_spy_underwater_trading_sessions": mc_spy["relative_underwater_trading_sessions"],
            "rel_spy_underwater_calendar_days": mc_spy["relative_underwater_calendar_days"],
            "rel_spy_underwater_months": mc_spy["relative_underwater_months"],
            "rel_spy_current_relative_drawdown": mc_spy["current_relative_drawdown"],
            "rel_spy_distance_from_peak": mc_spy["distance_from_relative_peak"],
            "rel_spy_currently_underwater": mc_spy["currently_underwater"],
        }
    )

    if qqq is not None:
        qqq_ret = _as_returns(qqq, net.index)
        out.update(_beta_block(qqq, "qqq"))
        mc_q = metric_c_relative_stats(net, qqq_ret)
        out.update(
            {
                "rel_qqq_final_relative_nav": mc_q["final_relative_nav"],
                "rel_qqq_relative_cagr": mc_q["relative_cagr"],
                "rel_qqq_max_dd": mc_q["relative_max_dd"],
                "rel_qqq_underwater_trading_sessions": mc_q["relative_underwater_trading_sessions"],
                "rel_qqq_underwater_calendar_days": mc_q["relative_underwater_calendar_days"],
                "rel_qqq_underwater_months": mc_q["relative_underwater_months"],
                "rel_qqq_current_relative_drawdown": mc_q["current_relative_drawdown"],
                "rel_qqq_distance_from_peak": mc_q["distance_from_relative_peak"],
                "rel_qqq_currently_underwater": mc_q["currently_underwater"],
            }
        )

    if equal_weight is not None:
        ew_ret = _as_returns(equal_weight, net.index)
        mc_ew = metric_c_relative_stats(net, ew_ret)
        out.update(
            {
                "rel_ew9_final_relative_nav": mc_ew["final_relative_nav"],
                "rel_ew9_relative_cagr": mc_ew["relative_cagr"],
                "rel_ew9_max_dd": mc_ew["relative_max_dd"],
                "rel_ew9_underwater_trading_sessions": mc_ew["relative_underwater_trading_sessions"],
                "rel_ew9_underwater_calendar_days": mc_ew["relative_underwater_calendar_days"],
                "rel_ew9_underwater_months": mc_ew["relative_underwater_months"],
                "rel_ew9_current_relative_drawdown": mc_ew["current_relative_drawdown"],
                "rel_ew9_distance_from_peak": mc_ew["distance_from_relative_peak"],
                "rel_ew9_currently_underwater": mc_ew["currently_underwater"],
            }
        )

    if crisis_windows:
        for name, (start, end) in crisis_windows.items():
            out[f"crisis_{name}_return"] = window_return(net, start, end)

    return out
