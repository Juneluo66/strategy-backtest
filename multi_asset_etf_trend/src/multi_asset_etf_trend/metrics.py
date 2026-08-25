"""Performance metrics and formal Metric C relative wealth."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

METRIC_C_DEFINITION = (
    "relative_nav_t = nav_strategy_t / nav_benchmark_t "
    "(both rebased to 1.0 at the first common date). "
    "Relative underwater = relative_nav / relative_nav.cummax() - 1."
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
    return {
        "final_relative_nav": final_rel,
        "relative_cagr": rel_cagr,
        "relative_max_dd": float(frame["relative_drawdown"].min()),
        "relative_underwater_trading_sessions": float(longest_td),
        "relative_underwater_calendar_days": float(cal_days),
        "relative_underwater_months": float(months),
        "current_relative_drawdown": float(frame["relative_drawdown"].iloc[-1]),
        "currently_underwater": bool(frame["relative_drawdown"].iloc[-1] < -1e-15),
        "n_common_observations": int(len(frame)),
        "common_start": str(frame.index[0].date()),
        "common_end": str(frame.index[-1].date()),
        "definition": METRIC_C_DEFINITION,
        "frame": frame,
    }


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
    sixty_forty: Optional[pd.Series] = None,
    bil: Optional[pd.Series] = None,
    turnover_status: str = "measured",
    crisis_windows: Optional[dict] = None,
) -> dict:
    net = equity["net_return"].dropna()
    gross = equity["gross_return"].dropna() if "gross_return" in equity else net
    if net.empty:
        return {"status": "EMPTY"}
    years = max((net.index.max() - net.index.min()).days / 365.25, 1 / 12)
    eq = (1 + net).cumprod()
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
    sharpe = (
        float(net.mean() / net.std(ddof=1) * np.sqrt(252))
        if len(net) > 1 and net.std(ddof=1)
        else np.nan
    )

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

    gross_cagr = (
        float((1 + gross).cumprod().iloc[-1] ** (1 / years) - 1) if len(gross) else np.nan
    )
    cost_drag = gross_cagr - cagr if pd.notna(gross_cagr) else np.nan

    spy_s = spy.reindex(net.index)
    if spy_s.dropna().abs().median() > 0.05:
        spy_ret = spy_s.pct_change(fill_method=None)
    else:
        spy_ret = spy_s
    spy_ret = spy_ret.reindex(net.index)
    aligned_spy = pd.concat([net, spy_ret], axis=1).dropna()
    if len(aligned_spy) > 5:
        corr = float(aligned_spy.corr().iloc[0, 1])
        cov = float(np.cov(aligned_spy.iloc[:, 0], aligned_spy.iloc[:, 1])[0, 1])
        var_b = float(np.var(aligned_spy.iloc[:, 1], ddof=1))
        beta = cov / var_b if var_b > 0 else np.nan
        up = aligned_spy[aligned_spy.iloc[:, 1] > 0]
        down = aligned_spy[aligned_spy.iloc[:, 1] < 0]
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
    else:
        corr = beta = up_cap = down_cap = np.nan

    mc_spy = metric_c_relative_stats(net, spy_ret)
    avg_bil = float(equity["w_bil"].mean()) if "w_bil" in equity.columns else np.nan

    out = {
        "cagr": cagr,
        "volatility": vol,
        "sharpe": sharpe,
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
        "avg_bil_weight": avg_bil,
        "corr_spy": corr,
        "beta_spy": beta,
        "up_capture": up_cap,
        "down_capture": down_cap,
        "turnover_status": turnover_status,
        "cost_total": cost_total,
        "start": str(net.index.min().date()),
        "end": str(net.index.max().date()),
        "n_days": int(len(net)),
        # Metric C vs SPY
        "rel_spy_final_relative_nav": mc_spy["final_relative_nav"],
        "rel_spy_relative_cagr": mc_spy["relative_cagr"],
        "rel_spy_max_dd": mc_spy["relative_max_dd"],
        "rel_spy_underwater_trading_sessions": mc_spy["relative_underwater_trading_sessions"],
        "rel_spy_underwater_calendar_days": mc_spy["relative_underwater_calendar_days"],
        "rel_spy_underwater_months": mc_spy["relative_underwater_months"],
        "rel_spy_currently_underwater": mc_spy["currently_underwater"],
        "rel_definition": METRIC_C_DEFINITION,
    }
    if bil is not None:
        bil_ret = bil.reindex(net.index)
        if bil_ret.dropna().abs().median() > 0.05:
            bil_ret = bil_ret.pct_change(fill_method=None)
        bil_stats = metric_c_relative_stats(net, bil_ret)  # relative wealth vs cash
        bil_cagr_years = max((net.index.max() - net.index.min()).days / 365.25, 1 / 12)
        bil_eq = (1 + bil_ret.dropna()).cumprod()
        if len(bil_eq):
            out["bil_cagr"] = float(bil_eq.iloc[-1] ** (1 / bil_cagr_years) - 1)
        out["cagr_minus_bil"] = out["cagr"] - out.get("bil_cagr", np.nan)

    if sixty_forty is not None:
        sf = sixty_forty.reindex(net.index)
        if sf.dropna().abs().median() > 0.05:
            sf = sf.pct_change(fill_method=None)
        mc_sf = metric_c_relative_stats(net, sf)
        out.update(
            {
                "rel_60_40_final_relative_nav": mc_sf["final_relative_nav"],
                "rel_60_40_relative_cagr": mc_sf["relative_cagr"],
                "rel_60_40_max_dd": mc_sf["relative_max_dd"],
                "rel_60_40_underwater_trading_sessions": mc_sf[
                    "relative_underwater_trading_sessions"
                ],
                "rel_60_40_underwater_calendar_days": mc_sf["relative_underwater_calendar_days"],
                "rel_60_40_underwater_months": mc_sf["relative_underwater_months"],
                "rel_60_40_currently_underwater": mc_sf["currently_underwater"],
            }
        )

    if crisis_windows:
        for name, (start, end) in crisis_windows.items():
            out[f"crisis_{name}_return"] = window_return(net, start, end)

    return out
