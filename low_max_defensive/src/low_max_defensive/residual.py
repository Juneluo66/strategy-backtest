"""Within vol/beta buckets: all vs exclude high-MAX 20% (no parameter search)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from max_effect_vix.factors import max_factor, monthly_signal_dates

from .metrics_ext import cagr, max_drawdown, sharpe
from .portfolio_bt import equal_weights


def _bucket_labels(series: pd.Series, n_buckets: int = 3) -> pd.Series:
    valid = series.dropna()
    if len(valid) < n_buckets * 5:
        return pd.Series(index=series.index, dtype=object)
    try:
        return pd.qcut(series, n_buckets, labels=[f"B{i+1}" for i in range(n_buckets)], duplicates="drop")
    except ValueError:
        return pd.Series(index=series.index, dtype=object)


def residual_exclusion_experiment(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    membership_on,
    *,
    lookback: int,
    top_returns: int,
    min_dollar_volume: float,
    one_way_bps: float,
    exclude_frac: float = 0.20,
    control: str = "vol",
    n_buckets: int = 3,
) -> pd.DataFrame:
    """
    For each rebalance, assign stocks to control buckets (vol or beta), then form:
      - all names in bucket (EW)
      - exclude highest MAX exclude_frac within bucket (EW)
    Aggregate daily portfolio as equal-weight across bucket portfolios (bucket-neutral).
    """
    common = opens.index.intersection(closes.index).intersection(volumes.index)
    opens, closes, volumes = (f.reindex(common).sort_index() for f in (opens, closes, volumes))
    returns = closes.pct_change(fill_method=None)
    factors = returns.apply(max_factor, lookback=lookback, top_returns=top_returns)
    dollar_volume = (closes * volumes).rolling(lookback, min_periods=lookback).mean()
    vol60 = returns.rolling(60, min_periods=40).std() * np.sqrt(252)
    mkt = returns.mean(axis=1)
    beta60 = returns.apply(lambda s: s.rolling(60, min_periods=40).cov(mkt) / mkt.rolling(60, min_periods=40).var())

    signal_dates = list(monthly_signal_dates(common))
    ordered = list(common)
    execute_map = {}
    for sd in signal_dates:
        pos = ordered.index(sd)
        if pos + 1 < len(ordered):
            execute_map[ordered[pos + 1]] = sd

    def _targets(date: pd.Timestamp, drop_high_max: bool) -> pd.Series:
        eligible = dollar_volume.loc[date].ge(min_dollar_volume)
        members = membership_on(date)
        eligible = eligible & pd.Series([c in members for c in closes.columns], index=closes.columns)
        fac = factors.loc[date].where(eligible).dropna()
        ctrl = (vol60 if control == "vol" else beta60).loc[date].reindex(fac.index)
        buckets = _bucket_labels(ctrl, n_buckets)
        pieces = []
        for b in buckets.dropna().unique():
            names = buckets[buckets == b].index.tolist()
            sub = fac.reindex(names).dropna()
            if drop_high_max and len(sub) >= 5:
                n_drop = int(np.floor(len(sub) * exclude_frac))
                keep = sub.sort_values(ascending=False).iloc[n_drop:].index.tolist()
            else:
                keep = sub.index.tolist()
            if keep:
                pieces.append(equal_weights(keep, 1.0))
        if not pieces:
            return pd.Series(dtype=float)
        by_bucket = [p / len(pieces) for p in pieces]
        return pd.concat(by_bucket).groupby(level=0).sum()

    weights_all = pd.Series(dtype=float)
    weights_ex = pd.Series(dtype=float)
    pending_all = pending_ex = None
    rows = []
    prev_close = None

    for date in common:
        open_prices = opens.loc[date]
        close_prices = closes.loc[date]
        g_all = g_ex = 0.0
        c_all = c_ex = 0.0
        if prev_close is not None:
            overnight = (open_prices / prev_close - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            if not weights_all.empty:
                g_all += float((weights_all.reindex(overnight.index, fill_value=0.0) * overnight).sum())
            if not weights_ex.empty:
                g_ex += float((weights_ex.reindex(overnight.index, fill_value=0.0) * overnight).sum())

        if date in execute_map:
            if pending_all is not None:
                turn = float(pending_all.sub(weights_all, fill_value=0.0).abs().sum())
                c_all += turn * one_way_bps / 10_000
                weights_all = pending_all
                pending_all = None
            if pending_ex is not None:
                turn = float(pending_ex.sub(weights_ex, fill_value=0.0).abs().sum())
                c_ex += turn * one_way_bps / 10_000
                weights_ex = pending_ex
                pending_ex = None

        if not weights_all.empty:
            intraday = (close_prices / open_prices - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            g_all += float((weights_all.reindex(intraday.index, fill_value=0.0) * intraday).sum())
            g_ex += float((weights_ex.reindex(intraday.index, fill_value=0.0) * intraday).sum()) if not weights_ex.empty else 0.0

        if date in set(signal_dates):
            pending_all = _targets(date, drop_high_max=False)
            pending_ex = _targets(date, drop_high_max=True)

        rows.append(
            {
                "date": date,
                "all_net": g_all - c_all,
                "ex_net": g_ex - c_ex,
            }
        )
        prev_close = close_prices

    frame = pd.DataFrame(rows).set_index("date")
    return pd.DataFrame(
        [
            {
                "control": control,
                "variant": "all_within_buckets",
                "net_cagr": cagr(frame["all_net"]),
                "net_sharpe": sharpe(frame["all_net"]),
                "max_drawdown": max_drawdown(frame["all_net"]),
            },
            {
                "control": control,
                "variant": f"exclude_high_max_{int(exclude_frac*100)}_within_buckets",
                "net_cagr": cagr(frame["ex_net"]),
                "net_sharpe": sharpe(frame["ex_net"]),
                "max_drawdown": max_drawdown(frame["ex_net"]),
            },
            {
                "control": control,
                "variant": "incremental_exclude_minus_all",
                "net_cagr": cagr(frame["ex_net"]) - cagr(frame["all_net"]),
                "net_sharpe": sharpe(frame["ex_net"]) - sharpe(frame["all_net"]),
                "max_drawdown": max_drawdown(frame["ex_net"]) - max_drawdown(frame["all_net"]),
            },
        ]
    )
