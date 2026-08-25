"""Strategy A multifactor and B momentum variants (H5 construction order)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from ..factors import combine_scores, momentum_12_1, winsorize_cross_section
from ..status import SIZE_BLOCKED


@dataclass
class TargetResult:
    weights: pd.Series
    audit: list[dict]
    status: str
    detail: str


def apply_buffer(
    scores: pd.Series,
    previous: set[str],
    *,
    n_holdings: int,
    entry_pct: float,
    exit_pct: float,
) -> list[str]:
    ranked = scores.dropna().sort_values(ascending=False)
    if ranked.empty:
        return []
    n = len(ranked)
    entry_cut = max(int(np.ceil(entry_pct * n)), n_holdings)
    exit_cut = max(int(np.ceil(exit_pct * n)), n_holdings)
    entry_set = set(ranked.head(entry_cut).index)
    exit_ok = set(ranked.head(exit_cut).index)
    held = []
    # Keep incumbents still inside exit band
    for symbol in previous:
        if symbol in exit_ok:
            held.append(symbol)
    # Fill with top entry names
    for symbol in ranked.index:
        if len(held) >= n_holdings:
            break
        if symbol in entry_set and symbol not in held:
            held.append(symbol)
    # If still short, take pure top ranks
    for symbol in ranked.index:
        if len(held) >= n_holdings:
            break
        if symbol not in held:
            held.append(symbol)
    return held[:n_holdings]


def equal_weight_caps(
    names: list[str],
    *,
    max_single: float = 0.04,
    sector_map: Optional[dict[str, str]] = None,
    max_sector: float = 0.25,
) -> pd.Series:
    if not names:
        return pd.Series(dtype=float)
    w = pd.Series(1.0 / len(names), index=names, dtype=float)
    w = w.clip(upper=max_single)
    w = w / w.sum()
    if sector_map:
        # Greedy sector cap: scale overweight sectors
        for _ in range(5):
            sectors = pd.Series({s: sector_map.get(s, "UNK") for s in w.index})
            sector_w = w.groupby(sectors).sum()
            overweight = sector_w[sector_w > max_sector]
            if overweight.empty:
                break
            for sector, total in overweight.items():
                members = sectors[sectors == sector].index
                w.loc[members] *= max_sector / total
            w = w / w.sum()
            w = w.clip(upper=max_single)
            w = w / w.sum()
    return w


def build_momentum_target(
    closes: pd.DataFrame,
    date: pd.Timestamp,
    eligible: pd.Series,
    previous: set[str],
    *,
    variant: str = "B0",
    n_holdings: int = 40,
    entry_pct: float = 0.10,
    exit_pct: float = 0.20,
    quality_ok: bool = False,
    quality_mask: Optional[pd.Series] = None,
    returns_for_vol: Optional[pd.DataFrame] = None,
) -> TargetResult:
    """B0–B3. Quality variants BLOCKED when quality_ok is False (H6)."""
    if variant != "B0" and not quality_ok:
        return TargetResult(
            pd.Series(dtype=float),
            [{"gate": "BLOCKED", "reason": "PIT_FUNDAMENTALS_REQUIRED"}],
            "BLOCKED",
            "B1–B3 require PIT quality fields",
        )
    calendar = closes.index
    mom = momentum_12_1(closes, date, calendar)
    mom = winsorize_cross_section(mom.where(eligible))
    if quality_mask is not None:
        mom = mom.where(quality_mask)
    # B2: volatility scale using trailing returns only
    if variant == "B2" and returns_for_vol is not None and date in returns_for_vol.index:
        vol = returns_for_vol.loc[:date].tail(63).std()
        mom = mom / vol.replace(0, np.nan)
    if variant in {"B0", "B3"}:
        names = apply_buffer(
            mom, previous, n_holdings=n_holdings, entry_pct=entry_pct, exit_pct=exit_pct
        )
    else:
        names = list(mom.dropna().sort_values(ascending=False).head(n_holdings).index)
    # Spike jump check audit (false momentum from one-day gap)
    audit = []
    if returns_for_vol is not None and date in returns_for_vol.index:
        day_ret = returns_for_vol.loc[:date].tail(21).max()
        for symbol in names:
            if symbol in day_ret.index and abs(float(day_ret[symbol])) > 0.25:
                audit.append({"symbol": symbol, "flag": "JUMP_RISK", "max_21d": float(day_ret[symbol])})
    weights = equal_weight_caps(names)
    return TargetResult(weights, audit, "OK", variant)


def build_multifactor_target(
    closes: pd.DataFrame,
    date: pd.Timestamp,
    eligible: pd.Series,
    previous: set[str],
    *,
    value: Optional[pd.Series] = None,
    quality: Optional[pd.Series] = None,
    n_holdings: int = 40,
    value_w: float = 0.30,
    quality_w: float = 0.35,
    mom_w: float = 0.35,
    entry_pct: float = 0.10,
    exit_pct: float = 0.20,
    fundamentals_ok: bool = False,
) -> TargetResult:
    if not fundamentals_ok or value is None or quality is None:
        return TargetResult(
            pd.Series(dtype=float),
            [{"gate": "BLOCKED", "reason": "PIT_FUNDAMENTALS_REQUIRED", "size": SIZE_BLOCKED}],
            "BLOCKED",
            "Strategy A blocked without filed-based SEC/value/quality factors",
        )
    mom = momentum_12_1(closes, date, closes.index).where(eligible)
    parts = {
        "value": winsorize_cross_section(value.where(eligible)),
        "quality": winsorize_cross_section(quality.where(eligible)),
        "momentum": winsorize_cross_section(mom),
    }
    score = combine_scores(parts, {"value": value_w, "quality": quality_w, "momentum": mom_w})
    names = apply_buffer(
        score, previous, n_holdings=n_holdings, entry_pct=entry_pct, exit_pct=exit_pct
    )
    return TargetResult(equal_weight_caps(names), [], "OK", "A")
