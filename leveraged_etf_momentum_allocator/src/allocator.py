"""Portfolio allocation engine."""
from __future__ import annotations

from typing import Optional

import pandas as pd


WEIGHTING_METHODS = ("equal_weight", "winner_take_all", "score_weight")


def allocate(
    momentum_scores: pd.Series,
    *,
    top_n: int,
    weighting: str,
    max_positions: Optional[int] = None,
    risk_off_weight: Optional[pd.Series] = None,
) -> pd.Series:
    """Return target weights summing to <= 1.0 (remainder is implicit cash)."""
    if weighting not in WEIGHTING_METHODS:
        raise ValueError(f"unsupported weighting: {weighting}")

    if risk_off_weight is not None and not risk_off_weight.empty:
        w = risk_off_weight.copy()
        total = float(w.sum())
        if total > 1.0 + 1e-9:
            w = w / total
        return w

    if momentum_scores.empty:
        return pd.Series(dtype=float)

    ranked = momentum_scores.sort_values(ascending=False)
    positive = ranked[ranked > 0]
    candidates = positive if not positive.empty else ranked
    n = min(int(top_n), len(candidates))
    if max_positions is not None:
        n = min(n, int(max_positions))
    selected = candidates.head(n)
    if selected.empty:
        return pd.Series(dtype=float)

    if weighting == "winner_take_all":
        weights = pd.Series({selected.index[0]: 1.0})
    elif weighting == "equal_weight":
        w = 1.0 / len(selected)
        weights = pd.Series({t: w for t in selected.index})
    else:  # score_weight
        total = float(selected.sum())
        if total <= 0:
            w = 1.0 / len(selected)
            weights = pd.Series({t: w for t in selected.index})
        else:
            weights = selected / total

    return weights.sort_index()
