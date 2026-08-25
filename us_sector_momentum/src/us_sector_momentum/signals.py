"""Pre-registered sector momentum signals — three frozen versions only."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .calendar import month_end_index

TOP_N = 3
BUFFER_RANK = 4


def month_end_closes(closes: pd.DataFrame) -> pd.DataFrame:
    ends = month_end_index(closes.index)
    return closes.reindex(ends)


def skip_month_total_return(month_closes: pd.DataFrame, months_ago_far: int, months_ago_near: int = 1) -> pd.DataFrame:
    """
    Total return from `months_ago_far` month-ends ago to `months_ago_near` month-ends ago.

    Classic 12-1: far=12, near=1 → close[t-1] / close[t-12] - 1 (excludes most recent month).
    Classic 6-1: far=6, near=1.
    """
    if months_ago_far <= months_ago_near:
        raise ValueError("months_ago_far must be > months_ago_near")
    return month_closes.shift(months_ago_near) / month_closes.shift(months_ago_far) - 1.0


def rank_percentile_high_best(row: pd.Series) -> pd.Series:
    """
    Cross-sectional rank percentile in [0, 1]; higher raw value → higher percentile.
    Ties: average rank. With n=9: best → 1.0, worst → 0.0 via (rank-1)/(n-1).
    """
    valid = row.dropna()
    if len(valid) < 2:
        return pd.Series(np.nan, index=row.index)
    # rank 1 = worst, n = best
    ranks = valid.rank(method="average", ascending=True)
    n = len(valid)
    pct = (ranks - 1.0) / (n - 1.0)
    out = pd.Series(np.nan, index=row.index)
    out.loc[pct.index] = pct
    return out


def equal_top_n_weights(names: list[str], universe: list[str], top_n: int = TOP_N) -> pd.Series:
    if len(names) != top_n:
        raise ValueError(f"expected exactly {top_n} names, got {names}")
    w = {s: 0.0 for s in universe}
    for name in names:
        w[name] = 1.0 / top_n
    return pd.Series(w, dtype=float)


def select_top_n(scores: pd.Series, n: int = TOP_N) -> list[str]:
    ordered = scores.sort_values(ascending=False)
    # Deterministic tie-break: score desc, then ticker asc
    ordered = ordered.reset_index()
    ordered.columns = ["symbol", "score"]
    ordered = ordered.sort_values(["score", "symbol"], ascending=[False, True])
    return list(ordered["symbol"].head(n))


def apply_top3_buffer(
    prev_holdings: Optional[list[str]],
    scores: pd.Series,
    *,
    top_n: int = TOP_N,
    buffer_rank: int = BUFFER_RANK,
) -> list[str]:
    """
    Keep held names while their new rank is still within top `buffer_rank`.
    Fill vacancies by current score order. Always return exactly `top_n` names.
    """
    ordered = scores.sort_values(ascending=False)
    rank_table = ordered.reset_index()
    rank_table.columns = ["symbol", "score"]
    rank_table = rank_table.sort_values(["score", "symbol"], ascending=[False, True]).reset_index(drop=True)
    rank_table["rank"] = np.arange(1, len(rank_table) + 1)
    rank_map = dict(zip(rank_table["symbol"], rank_table["rank"]))
    score_order = list(rank_table["symbol"])

    if not prev_holdings:
        return score_order[:top_n]

    kept: list[str] = []
    for sym in prev_holdings:
        if sym in rank_map and rank_map[sym] <= buffer_rank:
            kept.append(sym)
        if len(kept) == top_n:
            break

    for sym in score_order:
        if len(kept) >= top_n:
            break
        if sym not in kept:
            kept.append(sym)
    return kept[:top_n]


def build_monthly_targets(
    closes: pd.DataFrame,
    sectors: list[str],
    version: str,
    *,
    top_n: int = TOP_N,
    buffer_rank: int = BUFFER_RANK,
) -> dict[pd.Timestamp, pd.Series]:
    """Month-end close signals. Always 100% invested in `top_n` equal weights."""
    me = month_end_closes(closes[sectors])
    r12_1 = skip_month_total_return(me, 12, 1)
    r6_1 = skip_month_total_return(me, 6, 1)

    targets: dict[pd.Timestamp, pd.Series] = {}
    prev: Optional[list[str]] = None

    for date in me.index:
        if version == "base_12_1_top3":
            scores = r12_1.loc[date, sectors]
            if scores.isna().any():
                continue
            names = select_top_n(scores, n=top_n)
        elif version in {"composite_6_1_12_1_top3", "composite_top3_buffer"}:
            s6 = r6_1.loc[date, sectors]
            s12 = r12_1.loc[date, sectors]
            if s6.isna().any() or s12.isna().any():
                continue
            p6 = rank_percentile_high_best(s6)
            p12 = rank_percentile_high_best(s12)
            scores = 0.5 * p6 + 0.5 * p12
            if scores.isna().any():
                continue
            if version == "composite_6_1_12_1_top3":
                names = select_top_n(scores, n=top_n)
            else:
                names = apply_top3_buffer(prev, scores, top_n=top_n, buffer_rank=buffer_rank)
                prev = names
        else:
            raise ValueError(f"unknown version: {version}")

        tgt = equal_top_n_weights(names, sectors, top_n=top_n)
        if abs(float(tgt.sum()) - 1.0) > 1e-8:
            raise ValueError(f"weights sum {tgt.sum()} on {date.date()}")
        if (tgt < -1e-12).any():
            raise ValueError("negative weight")
        if (tgt > 0).sum() != top_n:
            raise ValueError("must hold exactly top_n names")
        targets[pd.Timestamp(date)] = tgt
        if version == "composite_6_1_12_1_top3":
            prev = names
        elif version == "base_12_1_top3":
            prev = names
    return targets
