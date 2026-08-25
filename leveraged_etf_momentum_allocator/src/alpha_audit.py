"""Alpha source audit — explain incremental return vs TQQQ buy-and-hold."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from metrics import ann_vol, cagr, compute_metrics, max_drawdown, sharpe, sortino


def _period_return(rets: pd.Series) -> float:
    r = rets.dropna()
    if r.empty:
        return float("nan")
    return float((1 + r).prod() - 1)


def _max_dd_series(rets: pd.Series) -> float:
    return max_drawdown(rets)


def tqqq_counterfactual_returns(equity: pd.DataFrame, closes: pd.DataFrame) -> pd.Series:
    """Daily TQQQ close-to-close aligned to equity calendar."""
    tqqq = closes["TQQQ"].reindex(equity.index)
    return tqqq.pct_change().fillna(0.0)


def tqqq_avoidance_episodes(
    signal_log: pd.DataFrame,
    equity: pd.DataFrame,
    closes: pd.DataFrame,
) -> pd.DataFrame:
    """Episodes: exit TQQQ until next re-entry to TQQQ."""
    if signal_log.empty:
        return pd.DataFrame()
    log = signal_log.sort_values("date").reset_index(drop=True)
    tqqq_ret = tqqq_counterfactual_returns(equity, closes)
    episodes: list[dict] = []

    in_episode = False
    start_idx = 0
    exit_reason = ""
    entry_target = ""

    for i, row in log.iterrows():
        target = row["target"]
        prev = row.get("previous_target")
        if not in_episode and prev == "TQQQ" and target != "TQQQ":
            in_episode = True
            start_idx = i
            exit_reason = str(row.get("branch_path", ""))
            entry_target = target
        elif in_episode and target == "TQQQ":
            end_idx = i - 1
            if end_idx >= start_idx:
                episodes.append(
                    _episode_row(log, equity, tqqq_ret, start_idx, end_idx, exit_reason, entry_target)
                )
            in_episode = False

    if in_episode:
        episodes.append(
            _episode_row(
                log, equity, tqqq_ret, start_idx, len(log) - 1, exit_reason, entry_target
            )
        )

    df = pd.DataFrame(episodes)
    if not df.empty:
        df = df.sort_values("difference", ascending=False)
    return df


def _episode_row(
    log, equity, tqqq_ret, start_idx, end_idx, exit_reason, entry_target
) -> dict:
    dates = log.iloc[start_idx:end_idx + 1]["date"]
    start = pd.Timestamp(dates.iloc[0])
    end = pd.Timestamp(dates.iloc[-1])
    mask = (equity.index >= start) & (equity.index <= end)
    strat_rets = equity.loc[mask, "net_return"]
    tqqq_slice = tqqq_ret.loc[mask]
    targets = log.iloc[start_idx:end_idx + 1]["target"].value_counts().to_dict()
    sr = _period_return(strat_rets)
    tr = _period_return(tqqq_slice)
    return {
        "start": str(start.date()),
        "end": str(end.date()),
        "trading_days": int(len(strat_rets)),
        "exit_reason": exit_reason,
        "entry_target": entry_target,
        "strategy_return": sr,
        "tqqq_return": tr,
        "difference": sr - tr,
        "max_drawdown_strategy": _max_dd_series(strat_rets),
        "max_drawdown_tqqq": _max_dd_series(tqqq_slice),
        "targets_used": str(targets),
    }


def avoided_loss_attribution(
    equity: pd.DataFrame,
    signal_log: pd.DataFrame,
    closes: pd.DataFrame,
) -> dict[str, Any]:
    """Non-TQQQ days: strategy vs TQQQ counterfactual. Not strict additive attribution."""
    tqqq_ret = tqqq_counterfactual_returns(equity, closes)
    log = signal_log.set_index("date")
    merged = equity.join(log[["target"]], how="inner")
    non_tqqq = merged[merged["target"] != "TQQQ"]
    in_tqqq = merged[merged["target"] == "TQQQ"]

    non_strat = _period_return(non_tqqq["net_return"])
    non_tqqq_cf_ret = tqqq_ret.reindex(non_tqqq.index).fillna(0)
    non_tqqq_total = _period_return(non_tqqq_cf_ret)

    tqqq_bh_total = _period_return(tqqq_ret.reindex(merged.index).fillna(0))
    strat_total = _period_return(merged["net_return"])

    # Sum of daily differences on non-TQQQ days (approximation, not additive)
    daily_diff = non_tqqq["net_return"] - non_tqqq_cf_ret
    avoided_loss_proxy = float(daily_diff.sum())

    return {
        "definition": (
            "avoided_loss_contribution = sum(daily strategy - TQQQ return) on non-TQQQ signal days. "
            "NOT strict additive attribution; compounding interaction ignored."
        ),
        "non_tqqq_days": int(len(non_tqqq)),
        "non_tqqq_strategy_cumulative_return": non_strat,
        "non_tqqq_tqqq_counterfactual_cumulative": non_tqqq_total,
        "non_tqqq_daily_diff_sum": avoided_loss_proxy,
        "tqqq_days_strategy_cumulative": _period_return(in_tqqq["net_return"]),
        "tqqq_days_tqqq_counterfactual": _period_return(
            tqqq_ret.reindex(in_tqqq.index).fillna(0)
        ),
        "full_period_strategy": strat_total,
        "full_period_tqqq_bh": tqqq_bh_total,
        "incremental_vs_tqqq_bh": strat_total - tqqq_bh_total,
        "verdict_hint": (
            "B dominates if non_tqqq_tqqq_counterfactual << 0 and daily_diff_sum large positive"
        ),
    }


def regime_attribution(
    signal_log: pd.DataFrame,
    equity: pd.DataFrame,
    closes: pd.DataFrame,
) -> pd.DataFrame:
    tqqq_ret = tqqq_counterfactual_returns(equity, closes)
    log = signal_log.set_index("date")
    merged = equity.join(log[["target", "market_regime"]], how="inner")
    merged["tqqq_ret"] = tqqq_ret.reindex(merged.index).fillna(0)
    rows = []
    for regime in ["BULL", "BEAR"]:
        g = merged[merged["market_regime"] == regime]
        if g.empty:
            continue
        sr = g["net_return"]
        tr = g["tqqq_ret"]
        rows.append(
            {
                "regime": regime,
                "days": len(g),
                "time_pct": len(g) / len(merged),
                "strategy_return": _period_return(sr),
                "tqqq_return": _period_return(tr),
                "cagr_equivalent": cagr(sr),
                "avg_daily_return": float(sr.mean()),
                "volatility": ann_vol(sr),
                "sharpe": sharpe(sr),
                "max_dd": max_drawdown(sr),
                "excess_vs_tqqq": _period_return(sr) - _period_return(tr),
            }
        )
    return pd.DataFrame(rows)


def bull_tree_comparison(
    original: dict,
    bull_always_tqqq: dict,
) -> dict[str, Any]:
    """BULL regime: original vs always TQQQ."""
    o_log = original["signal_log"]
    b_log = bull_always_tqqq["signal_log"]
    o_eq = original["equity"]
    b_eq = bull_always_tqqq["equity"]

    o_bull = o_log[o_log["market_regime"] == "BULL"].set_index("date")
    dates = o_bull.index.intersection(o_eq.index)
    o_rets = o_eq.loc[dates, "net_return"]
    b_rets = b_eq.reindex(dates)["net_return"].fillna(0)

    uvxy_days = int((o_bull["target"] == "UVXY").sum())
    return {
        "bull_days": len(dates),
        "uvxy_signal_days": uvxy_days,
        "uvxy_pct_of_bull": uvxy_days / len(dates) if len(dates) else 0,
        "original_bull_cumulative": _period_return(o_rets),
        "always_tqqq_bull_cumulative": _period_return(b_rets),
        "incremental_vs_always_tqqq": _period_return(o_rets) - _period_return(b_rets),
        "original_bull_max_dd": max_drawdown(o_rets),
        "always_tqqq_bull_max_dd": max_drawdown(b_rets),
    }


def bear_tree_comparison(
    results: dict[str, dict],
) -> pd.DataFrame:
    """Bear regime metrics for multiple strategies."""
    rows = []
    for name, res in results.items():
        log = res["signal_log"]
        eq = res["equity"]
        bear_dates = log.loc[log["market_regime"] == "BEAR", "date"]
        bear_eq = eq.loc[eq.index.isin(bear_dates)]
        if bear_eq.empty:
            continue
        r = bear_eq["net_return"]
        rows.append(
            {
                "strategy": name,
                "bear_days": len(bear_eq),
                "bear_return": _period_return(r),
                "bear_cagr_equiv": cagr(r),
                "bear_sharpe": sharpe(r),
                "bear_max_dd": max_drawdown(r),
                "target_changes": int(log.loc[log["market_regime"] == "BEAR", "target_changed"].sum()),
            }
        )
    return pd.DataFrame(rows)


def crash_episodes(
    equity: pd.DataFrame,
    closes: pd.DataFrame,
    signal_log: pd.DataFrame,
    benchmarks: dict[str, pd.Series],
    *,
    episodes: Optional[list[dict]] = None,
) -> pd.DataFrame:
    """Report named crash windows + TQQQ DD > 30% episodes."""
    tqqq = closes["TQQQ"]
    tqqq_ret = tqqq.pct_change()
    named = episodes or [
        {"name": "2015 correction", "start": "2015-08-01", "end": "2015-09-30"},
        {"name": "2018 Q4", "start": "2018-10-01", "end": "2018-12-31"},
        {"name": "2020 COVID", "start": "2020-02-15", "end": "2020-04-30"},
        {"name": "2022 bear", "start": "2022-01-01", "end": "2022-12-31"},
    ]
    rows = []
    log = signal_log.set_index("date") if not signal_log.empty else pd.DataFrame()

    for ep in named:
        start, end = pd.Timestamp(ep["start"]), pd.Timestamp(ep["end"])
        eq_mask = (equity.index >= start) & (equity.index <= end)
        if not eq_mask.any():
            continue
        eq_slice = equity.loc[eq_mask]
        tqqq_slice = tqqq_ret.reindex(eq_slice.index).fillna(0)
        spy_slice = closes["SPY"].pct_change().reindex(eq_slice.index).fillna(0)
        qqq_slice = closes["QQQ"].pct_change().reindex(eq_slice.index).fillna(0)
        sr = _period_return(eq_slice["net_return"])
        row = {
            "episode": ep["name"],
            "start": str(start.date()),
            "end": str(end.date()),
            "original_return": sr,
            "tqqq_return": _period_return(tqqq_slice),
            "qqq_return": _period_return(qqq_slice),
            "spy_return": _period_return(spy_slice),
        }
        for k, ser in benchmarks.items():
            row[f"{k}_return"] = _period_return(ser.reindex(eq_slice.index).fillna(0))
        if not log.empty:
            sub = log.loc[(log.index >= start) & (log.index <= end)]
            row["dominant_target"] = sub["target"].mode().iloc[0] if len(sub) else ""
            row["target_changes"] = int(sub["target_changed"].sum()) if "target_changed" in sub else 0
        rows.append(row)

    # TQQQ drawdown > 30% rolling episodes
    nav = (1 + tqqq_ret.fillna(0)).cumprod()
    dd = nav / nav.cummax() - 1
    in_dd = dd < -0.30
    # simplified: report worst rolling 63-day tqqq return
    roll = tqqq_ret.rolling(63).apply(lambda x: (1 + x).prod() - 1, raw=False)
    worst_idx = roll.idxmin()
    if worst_idx is not None and pd.notna(roll.min()):
        wstart = worst_idx - pd.Timedelta(days=63)
        mask_eq = (equity.index >= wstart) & (equity.index <= worst_idx)
        rows.append(
            {
                "episode": "TQQQ worst 63d window",
                "start": str(wstart.date()),
                "end": str(worst_idx.date()),
                "original_return": _period_return(equity.loc[mask_eq, "net_return"]),
                "tqqq_return": float(roll.min()),
            }
        )

    return pd.DataFrame(rows)


def metrics_row(result: dict, label: str) -> dict[str, Any]:
    m = compute_metrics(result["equity"], result["trades"], label=label)
    return {
        "label": label,
        "cagr": m["cagr_net"],
        "sharpe": m["sharpe_rf0"],
        "sortino": m["sortino_rf0"],
        "max_dd": m["max_drawdown"],
        "calmar": m["calmar"],
        "volatility": m["annualized_volatility"],
        "final_wealth": m["final_wealth_net"],
        "turnover": m["annual_turnover"],
        "trades": m["number_of_trades"],
    }
