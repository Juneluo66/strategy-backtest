"""Pre-registered multi-asset absolute-momentum signals vs BIL."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .calendar import month_end_index

RISK_N = 8  # canonical universe size
LOOKBACKS = (3, 6, 12)
VOL_LOOKBACK = 63


def _slot(risk: list[str]) -> float:
    """Equal budget per risk name in the active pool (1/8 for canonical universe)."""
    n = len(risk)
    if n < 1:
        raise ValueError("empty risk pool")
    return 1.0 / n


def month_end_closes(closes: pd.DataFrame) -> pd.DataFrame:
    ends = month_end_index(closes.index)
    return closes.reindex(ends)


def rolling_month_total_return(month_closes: pd.DataFrame, months: int) -> pd.DataFrame:
    """Past N calendar-month total returns using month-end Adj Close."""
    return month_closes / month_closes.shift(months) - 1.0


def annualized_vol_63d(closes: pd.DataFrame, lookback: int = VOL_LOOKBACK) -> pd.DataFrame:
    """Trailing annualized vol from daily total returns ending on each date.

    Uses only data through that date (no lookahead). Never fillna(0).
    """
    rets = closes.pct_change(fill_method=None)
    daily_std = rets.rolling(lookback, min_periods=lookback).std(ddof=1)
    return daily_std * np.sqrt(252.0)


def _score_ensemble(rel_pos: dict[int, bool]) -> float:
    """score = (# horizons with positive relative return) / 3 ∈ {0, 1/3, 2/3, 1}."""
    hits = sum(1 for v in rel_pos.values() if v)
    return hits / 3.0


def target_base_12m_equal(
    risk: list[str],
    cash: str,
    r12_risk: pd.Series,
    r12_cash: float,
) -> pd.Series:
    """
    Each risk ETF owns a fixed 1/N budget (N = len(risk); 1/8 for canonical pool).
    If ETF 12m total return > BIL 12m total return → allocate that slot to ETF;
    else that slot goes to BIL. No renormalization across winners.
    """
    slot = _slot(risk)
    weights: dict[str, float] = {cash: 0.0}
    for symbol in risk:
        r = r12_risk.get(symbol, np.nan)
        if pd.isna(r) or pd.isna(r12_cash):
            # Incomplete history → park slot in cash (do not invent signal)
            weights[cash] = weights.get(cash, 0.0) + slot
            continue
        if float(r) > float(r12_cash):
            weights[symbol] = weights.get(symbol, 0.0) + slot
        else:
            weights[cash] = weights.get(cash, 0.0) + slot
    return pd.Series(weights, dtype=float)


def target_ensemble_equal(
    risk: list[str],
    cash: str,
    rel_flags: dict[str, dict[int, bool]],
) -> pd.Series:
    """
    score_i ∈ {0, 1/3, 2/3, 1}; weight_i = (1/N) * score_i;
    residual → BIL. No renormalization of risk sleeve to 100%.
    """
    slot = _slot(risk)
    weights: dict[str, float] = {}
    risk_sum = 0.0
    for symbol in risk:
        flags = rel_flags.get(symbol)
        if flags is None or any(v is None for v in flags.values()):
            score = 0.0
        else:
            score = _score_ensemble({k: bool(v) for k, v in flags.items()})
        w = slot * score
        if w > 0:
            weights[symbol] = w
        risk_sum += w
    residual = max(0.0, 1.0 - risk_sum)
    if residual > 1e-15:
        weights[cash] = residual
    elif cash not in weights:
        weights[cash] = 0.0
    return pd.Series(weights, dtype=float)


def target_ensemble_risk_balanced(
    risk: list[str],
    cash: str,
    rel_flags: dict[str, dict[int, bool]],
    vols: pd.Series,
) -> pd.Series:
    """
    Challenger weighting (documented carefully):

    1. On the full risk pool, compute inverse-vol base budgets:
         inv_i = 1 / vol_i   (vol_i = 63d annualized vol as of signal date)
         base_i = inv_i / sum_j inv_j     for ALL risk ETFs with valid vol
       Assets missing vol get base_i = 0 (their budget is not redistributed
       via dropping-then-renormalizing winners — they simply contribute 0
       inverse-vol mass; remaining valid assets share the unit budget).

    2. score_i identical to ensemble_equal.

    3. target_i = base_i * score_i

    4. residual = 1 - sum(target_i) → BIL

    Forbidden: drop negative-trend assets then renormalize survivors to 100%.
    Forbidden: rescale risk weights up to full investment after scoring.
    Cap: sum(risk weights) <= 1; no leverage.
    """
    inv: dict[str, float] = {}
    for symbol in risk:
        v = vols.get(symbol, np.nan)
        if pd.isna(v) or float(v) <= 0:
            continue
        inv[symbol] = 1.0 / float(v)
    inv_sum = sum(inv.values())
    base: dict[str, float] = {s: 0.0 for s in risk}
    if inv_sum > 0:
        for symbol, value in inv.items():
            base[symbol] = value / inv_sum

    weights: dict[str, float] = {}
    risk_sum = 0.0
    for symbol in risk:
        flags = rel_flags.get(symbol)
        if flags is None or any(v is None for v in flags.values()):
            score = 0.0
        else:
            score = _score_ensemble({k: bool(v) for k, v in flags.items()})
        w = base[symbol] * score
        # Numerical guard: never exceed 100% risk sleeve via float noise
        if w > 0:
            weights[symbol] = w
        risk_sum += w
    if risk_sum > 1.0 + 1e-10:
        raise ValueError(f"risk weight sum {risk_sum} exceeds 100% — formula bug")
    residual = max(0.0, 1.0 - risk_sum)
    weights[cash] = residual
    return pd.Series(weights, dtype=float)


def build_monthly_targets(
    closes: pd.DataFrame,
    risk: list[str],
    cash: str,
    version: str,
    *,
    vol_lookback: int = VOL_LOOKBACK,
) -> dict[pd.Timestamp, pd.Series]:
    """Month-end close signals for a pre-registered version. No lookahead."""
    cols = risk + [cash]
    me = month_end_closes(closes[cols])
    r3 = rolling_month_total_return(me, 3)
    r6 = rolling_month_total_return(me, 6)
    r12 = rolling_month_total_return(me, 12)
    vol_daily = annualized_vol_63d(closes[risk], lookback=vol_lookback)
    vol_me = vol_daily.reindex(me.index)

    targets: dict[pd.Timestamp, pd.Series] = {}
    for date in me.index:
        # Require cash 12m available at minimum for absolute momentum gate
        if pd.isna(r12.at[date, cash]):
            continue
        if any(pd.isna(r12.at[date, s]) for s in risk):
            # Wait until all risk assets have 12m history on common panel
            continue

        rel_flags: dict[str, dict[int, Optional[bool]]] = {}
        for symbol in risk:
            flags: dict[int, Optional[bool]] = {}
            for horizon, panel in ((3, r3), (6, r6), (12, r12)):
                etf_r = panel.at[date, symbol]
                bil_r = panel.at[date, cash]
                if pd.isna(etf_r) or pd.isna(bil_r):
                    flags[horizon] = None
                else:
                    flags[horizon] = bool(float(etf_r) > float(bil_r))
            rel_flags[symbol] = flags

        if version == "base_12m_equal":
            tgt = target_base_12m_equal(
                risk, cash, r12.loc[date, risk], float(r12.at[date, cash])
            )
        elif version == "ensemble_equal":
            # Need 3/6/12 all defined for scoring consistency
            if any(any(v is None for v in f.values()) for f in rel_flags.values()):
                continue
            tgt = target_ensemble_equal(risk, cash, rel_flags)  # type: ignore[arg-type]
        elif version == "ensemble_risk_balanced":
            if any(any(v is None for v in f.values()) for f in rel_flags.values()):
                continue
            vols = vol_me.loc[date, risk]
            if vols.isna().any():
                continue
            tgt = target_ensemble_risk_balanced(
                risk, cash, rel_flags, vols  # type: ignore[arg-type]
            )
        else:
            raise ValueError(f"unknown version: {version}")

        # Sanity: weights sum to ~1, no shorts, no leverage
        s = float(tgt.sum())
        if abs(s - 1.0) > 1e-8:
            raise ValueError(f"weights sum {s} on {date.date()} version={version}")
        if (tgt < -1e-12).any():
            raise ValueError("negative weight")
        targets[pd.Timestamp(date)] = tgt
    return targets
