"""Portfolio construction: filters, category cap, hysteresis, regime Top-K, cash fill."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from .signals import score_column


@dataclass
class PortfolioState:
    holdings: list[str] = field(default_factory=list)  # risk holdings only
    scores: dict[str, float] = field(default_factory=dict)


def _eligible_mask(day: pd.DataFrame, *, trend_consistency: bool, vol_adjust: bool) -> pd.Series:
    col = score_column(vol_adjust)
    ok = day["above_ma"] & day[col].notna()
    if vol_adjust:
        ok = ok & day["sigma_60d"].notna() & (day["sigma_60d"] > 0)
    if trend_consistency:
        ok = ok & day["trend_consistent"]
    return ok


def apply_category_constraint(
    day: pd.DataFrame,
    category_map: dict[str, str],
    score_col: str,
) -> tuple[pd.DataFrame, list[dict]]:
    """Keep the strongest symbol per asset class."""
    audit: list[dict] = []
    keep: list[str] = []
    grouped: dict[str, list[str]] = {}
    for symbol in day["symbol"].tolist():
        category = category_map.get(symbol, symbol)
        grouped.setdefault(category, []).append(symbol)
    for category, symbols in grouped.items():
        subset = day[day["symbol"].isin(symbols)].sort_values(score_col, ascending=False)
        winner = str(subset.iloc[0]["symbol"])
        keep.append(winner)
        for symbol in symbols:
            if symbol != winner:
                audit.append(
                    {
                        "symbol": symbol,
                        "reason": "category_capped",
                        "category": category,
                        "winner": winner,
                    }
                )
    return day[day["symbol"].isin(keep)].copy(), audit


def resolve_top_k(
    *,
    regime_sizing: bool,
    default_top_k: int,
    spy_above_ma: Optional[bool],
    n_eligible: int,
) -> tuple[int, str]:
    if n_eligible == 0:
        return 0, "all_risk_below_ma"
    if not regime_sizing:
        return default_top_k, "fixed_topk"
    if spy_above_ma is True:
        return default_top_k, "regime_risk_on"
    if spy_above_ma is False:
        return 1, "regime_risk_off_top1"
    return default_top_k, "regime_spy_unknown"


def hysteresis_select(
    ranked: list[str],
    scores: dict[str, float],
    state: PortfolioState,
    top_k: int,
    relative_threshold: float,
) -> tuple[list[str], list[dict]]:
    """
    Prefer incumbents unless a challenger exceeds incumbent * (1 + threshold).
    When starting empty, take top_k by score.
    """
    audit: list[dict] = []
    if top_k <= 0:
        return [], audit
    if not state.holdings:
        selected = ranked[:top_k]
        return selected, audit

    incumbents = [h for h in state.holdings if h in scores]
    selected = list(incumbents)
    # Drop incumbents no longer eligible.
    dropped = [h for h in state.holdings if h not in scores]
    for symbol in dropped:
        audit.append({"symbol": symbol, "reason": "incumbent_ineligible"})

    # Fill vacancies from ranked challengers.
    while len(selected) < top_k:
        for challenger in ranked:
            if challenger not in selected:
                selected.append(challenger)
                audit.append({"symbol": challenger, "reason": "fill_vacancy"})
                break
        else:
            break

    # Attempt replacements of weakest incumbents by stronger challengers.
    if len(selected) > top_k:
        selected = sorted(selected, key=lambda s: scores.get(s, -np.inf), reverse=True)[:top_k]

    challengers = [s for s in ranked if s not in selected]
    for challenger in challengers:
        if len(selected) < top_k:
            selected.append(challenger)
            continue
        weakest = min(selected, key=lambda s: scores.get(s, -np.inf))
        weak_score = scores.get(weakest, -np.inf)
        chal_score = scores.get(challenger, -np.inf)
        if not np.isfinite(weak_score) or not np.isfinite(chal_score):
            continue
        # Relative 5%: challenger must be > incumbent * 1.05.
        # If incumbent score <= 0, require absolute edge of threshold on score units.
        if weak_score > 0:
            needed = weak_score * (1.0 + relative_threshold)
            ok = chal_score > needed
        else:
            needed = weak_score + relative_threshold
            ok = chal_score > needed
        if ok:
            selected[selected.index(weakest)] = challenger
            audit.append(
                {
                    "symbol": challenger,
                    "reason": "hysteresis_replace",
                    "replaced": weakest,
                    "challenger_score": chal_score,
                    "incumbent_score": weak_score,
                    "needed": needed,
                }
            )
        else:
            audit.append(
                {
                    "symbol": challenger,
                    "reason": "hysteresis_block",
                    "vs": weakest,
                    "challenger_score": chal_score,
                    "incumbent_score": weak_score,
                    "needed": needed,
                }
            )
            # Only try replacing the current weakest once per challenger walk;
            # stop after first blocked stronger challenger to avoid churn noise.
            break

    selected = sorted(selected, key=lambda s: scores.get(s, -np.inf), reverse=True)[:top_k]
    return selected, audit


def choose_holdings(
    day: pd.DataFrame,
    state: PortfolioState,
    *,
    vol_adjust: bool,
    category_constraint: bool,
    trend_consistency: bool,
    regime_sizing: bool,
    top_k: int,
    relative_threshold: float,
    category_map: dict[str, str],
    cash_symbol: str,
    use_hysteresis: bool = True,
    selection_mode: str = "topk",
) -> tuple[dict[str, float], PortfolioState, list[dict[str, Any]]]:
    """
    Return target weights (including cash), updated state, and audit events.
    """
    audit: list[dict[str, Any]] = []
    score_col = score_column(vol_adjust)
    if day.empty:
        weights = {cash_symbol: 1.0}
        return weights, PortfolioState(), [{"reason": "empty_panel", "cash": cash_symbol}]

    # equal_weight_eligible only needs MA filter (and optional trend consistency).
    if selection_mode == "equal_weight_eligible":
        eligible = day.loc[day["above_ma"]].copy()
        if trend_consistency:
            eligible = eligible.loc[eligible["trend_consistent"]].copy()
    else:
        eligible = day.loc[
            _eligible_mask(day, trend_consistency=trend_consistency, vol_adjust=vol_adjust)
        ].copy()

    for _, row in day.iterrows():
        symbol = str(row["symbol"])
        if symbol in set(eligible["symbol"].astype(str)):
            continue
        if not row["above_ma"]:
            audit.append({"symbol": symbol, "reason": "below_ma"})
        elif selection_mode != "equal_weight_eligible" and vol_adjust and (
            pd.isna(row["sigma_60d"]) or row["sigma_60d"] <= 0
        ):
            audit.append({"symbol": symbol, "reason": "vol_missing"})
        elif trend_consistency and not row["trend_consistent"]:
            audit.append({"symbol": symbol, "reason": "trend_inconsistent"})
        elif selection_mode != "equal_weight_eligible" and pd.isna(row[score_col]):
            audit.append({"symbol": symbol, "reason": "score_missing"})

    if category_constraint and not eligible.empty and selection_mode != "equal_weight_eligible":
        eligible, cat_audit = apply_category_constraint(eligible, category_map, score_col)
        audit.extend(cat_audit)

    spy_row = day[day["symbol"] == "SPY"]
    spy_above = bool(spy_row.iloc[0]["above_ma"]) if len(spy_row) else None

    if selection_mode == "equal_weight_eligible":
        if eligible.empty:
            weights = {cash_symbol: 1.0}
            audit.append({"reason": "full_cash", "cash": cash_symbol, "detail": "ew_none_eligible"})
            return weights, PortfolioState(), audit
        selected = eligible["symbol"].astype(str).tolist()
        w = 1.0 / len(selected)
        weights = {symbol: w for symbol in selected}
        new_state = PortfolioState(holdings=list(selected), scores={})
        audit.append({"reason": "equal_weight_eligible", "n": len(selected)})
        return weights, new_state, audit

    k, regime_reason = resolve_top_k(
        regime_sizing=regime_sizing,
        default_top_k=top_k,
        spy_above_ma=spy_above,
        n_eligible=len(eligible),
    )
    audit.append({"reason": "regime_topk", "top_k": k, "detail": regime_reason, "spy_above_ma": spy_above})

    if k == 0 or eligible.empty:
        weights = {cash_symbol: 1.0}
        return weights, PortfolioState(), audit

    ranked_df = eligible.sort_values(score_col, ascending=False)
    ranked = ranked_df["symbol"].astype(str).tolist()
    scores = {str(r["symbol"]): float(r[score_col]) for _, r in ranked_df.iterrows()}
    if use_hysteresis:
        selected, hyst_audit = hysteresis_select(ranked, scores, state, k, relative_threshold)
        audit.extend(hyst_audit)
    else:
        selected = ranked[:k]
        audit.append({"reason": "no_hysteresis", "selected": list(selected)})

    # Each filled Top-K slot gets 1/k; unfilled slots remain in cash (SGOV/BIL).
    weights: dict[str, float] = {}
    slot = 1.0 / float(k) if k > 0 else 0.0
    for symbol in selected:
        weights[symbol] = slot
    cash_weight = 1.0 - sum(weights.values())
    if cash_weight > 1e-12:
        weights[cash_symbol] = float(cash_weight)
        if cash_weight >= 1.0 - 1e-12:
            audit.append({"reason": "full_cash", "cash": cash_symbol})
        else:
            audit.append({"reason": "cash_fill", "cash": cash_symbol, "weight": cash_weight})

    new_state = PortfolioState(holdings=list(selected), scores={s: scores[s] for s in selected})
    return weights, new_state, audit
