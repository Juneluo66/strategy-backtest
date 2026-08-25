"""Overfitting and crisis dependence audit."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from alpha_audit import tqqq_avoidance_episodes, tqqq_counterfactual_returns
from metrics import ann_vol, cagr, calmar, compute_metrics, max_drawdown, sharpe


def _period_return(rets: pd.Series) -> float:
    r = rets.dropna()
    if r.empty:
        return float("nan")
    return float((1 + r).prod() - 1)


def bsv_counterfactual_returns(closes: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    return closes["BSV"].reindex(index).pct_change().fillna(0.0)


def terminal_branch_attribution(
    equity: pd.DataFrame,
    signal_log: pd.DataFrame,
    trades: pd.DataFrame,
    closes: pd.DataFrame,
) -> pd.DataFrame:
    if signal_log.empty:
        return pd.DataFrame()
    log = signal_log.copy()
    log["date"] = pd.to_datetime(log["date"])
    merged = equity.join(log.set_index("date")[["branch_id", "branch_rule", "target", "target_changed"]], how="inner")
    tqqq_ret = tqqq_counterfactual_returns(equity, closes)
    bsv_ret = bsv_counterfactual_returns(closes, equity.index)
    total_days = len(merged)

    rows: list[dict] = []
    for bid, grp in merged.groupby("branch_id"):
        if not bid or bid.startswith("BX"):
            continue
        dates = grp.index
        strat_rets = grp["net_return"]
        tqqq_slice = tqqq_ret.reindex(dates).fillna(0)
        bsv_slice = bsv_ret.reindex(dates).fillna(0)
        rule = grp["branch_rule"].iloc[0] if "branch_rule" in grp.columns else bid
        signal_count = int(len(grp))
        entry_count = int(grp["target_changed"].sum()) if "target_changed" in grp.columns else 0
        # Trade stats for this branch target
        target = grp["target"].iloc[0]
        trade_rets = _round_trip_returns(trades, target)
        rows.append(
            {
                "branch_id": bid,
                "branch_rule": rule,
                "signal_count": signal_count,
                "entry_count": entry_count,
                "days_held": signal_count,
                "time_pct": signal_count / total_days,
                "total_return_during_branch": _period_return(strat_rets),
                "pnl_contribution": float(strat_rets.sum()),
                "counterfactual_tqqq_return": _period_return(tqqq_slice),
                "counterfactual_bsv_return": _period_return(bsv_slice),
                "incremental_vs_tqqq": _period_return(strat_rets) - _period_return(tqqq_slice),
                "incremental_vs_bsv": _period_return(strat_rets) - _period_return(bsv_slice),
                "average_trade_return": float(np.mean(trade_rets)) if trade_rets else float("nan"),
                "median_trade_return": float(np.median(trade_rets)) if trade_rets else float("nan"),
                "win_rate": float((strat_rets > 0).mean()),
                "best_trade": float(max(trade_rets)) if trade_rets else float("nan"),
                "worst_trade": float(min(trade_rets)) if trade_rets else float("nan"),
                "best_episode_daily": float(strat_rets.max()),
                "worst_episode_daily": float(strat_rets.min()),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("incremental_vs_tqqq", ascending=False)
    return df


def _round_trip_returns(trades: pd.DataFrame, ticker: str) -> list[float]:
    if trades.empty:
        return []
    legs = trades[trades["ticker"] == ticker].sort_values("date")
    out: list[float] = []
    buy_px = None
    for _, row in legs.iterrows():
        if row["side"] == "buy":
            buy_px = float(row["execution_price"])
        elif row["side"] == "sell" and buy_px and buy_px > 0:
            out.append(float(row["execution_price"]) / buy_px - 1)
            buy_px = None
    return out


CRISIS_PERIODS = [
    ("2015-16", "2015-08-01", "2016-03-31"),
    ("2018", "2018-09-01", "2019-01-31"),
    ("COVID", "2020-02-01", "2020-06-30"),
    ("2022", "2022-01-01", "2022-12-31"),
]


def leave_one_crisis_out(
    equity: pd.DataFrame,
    closes: pd.DataFrame,
    exclude_periods: list[tuple[str, str, str]],
) -> pd.DataFrame:
    """Recompute metrics excluding crisis windows from daily returns."""
    rets = equity["net_return"].copy()
    tqqq = tqqq_counterfactual_returns(equity, closes)
    rows = []
    scenarios = [("Full sample", [])] + [(name, [(s, e)]) for name, s, e in exclude_periods]
    scenarios.append(("Exclude COVID+2022", [("2020-02-01", "2020-06-30"), ("2022-01-01", "2022-12-31")]))
    for label, periods in scenarios:
        mask = pd.Series(True, index=rets.index)
        for start, end in periods:
            mask &= ~((rets.index >= pd.Timestamp(start)) & (rets.index <= pd.Timestamp(end)))
        sr = rets.loc[mask]
        tr = tqqq.reindex(sr.index).fillna(0)
        rows.append(
            {
                "scenario": label,
                "days": len(sr),
                "cagr": cagr(sr),
                "sharpe": sharpe(sr),
                "max_dd": max_drawdown(sr),
                "tqqq_cagr": cagr(tr),
                "relative_cagr_vs_tqqq": cagr(sr) - cagr(tr),
            }
        )
    return pd.DataFrame(rows)


def detect_tqqq_crises(closes: pd.DataFrame, threshold: float = 0.30) -> list[tuple[str, str, str]]:
    """Peak-to-trough TQQQ drawdowns > threshold."""
    tqqq = closes["TQQQ"].dropna()
    nav = tqqq / tqqq.iloc[0]
    peak = nav.cummax()
    dd = nav / peak - 1
    episodes: list[tuple[str, str, str]] = []
    in_crisis = False
    start = None
    for date, d in dd.items():
        if d < -threshold and not in_crisis:
            in_crisis = True
            start = date
        elif in_crisis and d > -threshold / 2:
            episodes.append((f"TQQQ_DD_{start.date()}", str(start.date()), str(date.date())))
            in_crisis = False
    if in_crisis and start is not None:
        episodes.append((f"TQQQ_DD_{start.date()}", str(start.date()), str(tqqq.index[-1].date())))
    return episodes


def rolling_stability(
    equity: pd.DataFrame,
    closes: pd.DataFrame,
    *,
    window_years: int = 3,
) -> pd.DataFrame:
    """Monthly-end rolling windows."""
    rets = equity["net_return"]
    tqqq = tqqq_counterfactual_returns(equity, closes)
    spy = closes["SPY"].pct_change().reindex(rets.index).fillna(0)
    window_days = int(window_years * 252)
    rows = []
    # Month-end trading days only (avoid resample calendar mismatch)
    idx = rets.index
    month_ends = idx.to_series().groupby(idx.to_period("M")).last()
    for end_date in month_ends.values:
        end_date = pd.Timestamp(end_date)
        pos = idx.get_indexer([end_date], method="pad")[0]
        if pos < window_days:
            continue
        start_date = idx[pos - window_days]
        sl = rets.loc[start_date:end_date]
        tl = tqqq.loc[start_date:end_date]
        sp = spy.loc[start_date:end_date]
        rows.append(
            {
                "end_date": end_date,
                "window_years": window_years,
                "original_cagr": cagr(sl),
                "tqqq_cagr": cagr(tl),
                "spy_cagr": cagr(sp),
                "original_minus_tqqq": cagr(sl) - cagr(tl),
                "original_minus_spy": cagr(sl) - cagr(sp),
                "sharpe": sharpe(sl),
                "max_dd": max_drawdown(sl),
            }
        )
    return pd.DataFrame(rows)


def rolling_summary(rolling_df: pd.DataFrame) -> dict[str, float]:
    if rolling_df.empty:
        return {}
    rel = rolling_df["original_minus_tqqq"]
    rel_spy = rolling_df["original_minus_spy"]
    return {
        "pct_windows_beat_tqqq": float((rel > 0).mean()),
        "pct_windows_beat_spy": float((rel_spy > 0).mean()),
        "median_rel_cagr_vs_tqqq": float(rel.median()),
        "p25_rel_cagr_vs_tqqq": float(rel.quantile(0.25)),
        "p10_rel_cagr_vs_tqqq": float(rel.quantile(0.10)),
        "worst_window_rel_vs_tqqq": float(rel.min()),
    }


def crisis_concentration(
    signal_log: pd.DataFrame,
    equity: pd.DataFrame,
    closes: pd.DataFrame,
    final_wealth: float,
) -> dict[str, Any]:
    episodes = tqqq_avoidance_episodes(signal_log, equity, closes)
    if episodes.empty:
        return {"top1_pct": 0, "top3_pct": 0, "top5_pct": 0}
    # Estimate wealth contribution via difference * prior wealth proxy (not strict)
    total_diff = episodes["difference"].sum()
    sorted_ep = episodes.sort_values("difference", ascending=False)
    top1 = sorted_ep.iloc[0]["difference"]
    top3 = sorted_ep.head(3)["difference"].sum()
    top5 = sorted_ep.head(5)["difference"].sum()
    # Normalize by sum of positive differences
    pos_sum = sorted_ep[sorted_ep["difference"] > 0]["difference"].sum()
    if pos_sum <= 0:
        return {"top1_pct": 0, "top3_pct": 0, "top5_pct": 0, "episodes": sorted_ep.head(5)}
    return {
        "top1_episode": sorted_ep.iloc[0].to_dict(),
        "top1_pct_of_positive_diff": float(top1 / pos_sum),
        "top3_pct_of_positive_diff": float(top3 / pos_sum),
        "top5_pct_of_positive_diff": float(top5 / pos_sum),
        "crisis_concentration_risk": "HIGH" if top5 / pos_sum > 0.5 else "MEDIUM" if top5 / pos_sum > 0.35 else "LOW",
        "top5_episodes": sorted_ep.head(5),
    }


def random_neighborhood_distribution(
    cagr_samples: list[float],
    sharpe_samples: list[float],
    maxdd_samples: list[float],
    calmar_samples: list[float],
    original_cagr: float,
) -> dict[str, Any]:
    arr = np.array(cagr_samples)
    sh = np.array(sharpe_samples)
    md = np.array(maxdd_samples)
    ca = np.array(calmar_samples)
    pct_rank = float((arr < original_cagr).mean() * 100)
    overfit = "HIGH" if pct_rank > 90 else "MEDIUM" if pct_rank > 75 else "LOW"
    robust = "STRONGER" if np.median(arr) > 0.5 else "WEAK"
    return {
        "n_samples": len(arr),
        "cagr_median": float(np.median(arr)),
        "cagr_p25": float(np.percentile(arr, 25)),
        "cagr_p10": float(np.percentile(arr, 10)),
        "cagr_p5": float(np.percentile(arr, 5)),
        "cagr_worst": float(np.min(arr)),
        "sharpe_median": float(np.median(sh)),
        "maxdd_median": float(np.median(md)),
        "calmar_median": float(np.median(ca)),
        "original_cagr": original_cagr,
        "original_cagr_percentile": pct_rank,
        "PARAMETER_OVERFIT_RISK": overfit,
        "ROBUSTNESS": robust,
    }
