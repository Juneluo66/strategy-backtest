"""Simplification variants of conditional_leveraged_etf_rotation.

ORIGINAL select_target is never modified. All variants wrap or re-express
the same tree with standardized thresholds, collapsed conditions, feature
ablations, or pruned branches (BSV fallback).
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from original_strategy import (
    DecisionResult,
    StrategyState,
    get_max_rsi_asset,
    select_target,
)

# Natural round-number thresholds (ROBUST_CORE_V1 / STANDARDIZED)
ROBUST_CORE_V1_THRESHOLDS = {
    "qqq_rsi_overbought": 80,
    "spy_rsi_overbought": 80,
    "tqqq_rsi_oversold": 30,
    "spy_rsi_oversold": 30,
    "uvxy_high": 70,
    "uvxy_extreme": 80,
    "sqqq_rsi_branch_1": 30,
    "sqqq_rsi_branch_2": 30,
}

ROBUST_CORE_V1_PARAMS = {
    "rsi_period": 10,
    "spy_sma_period": 200,
    "qqq_sma_period": 20,
    "tqqq_sma_period": 20,
}


def select_target_options(
    state: StrategyState,
    thresholds: Optional[dict] = None,
    *,
    drop_sqqq_rsi: bool = False,
    drop_uvxy_rsi: bool = False,
    drop_qqq_sma: bool = False,
    drop_tqqq_sma: bool = False,
    drop_qqq_rsi: bool = False,
    drop_spy_rsi: bool = False,
    unify_sqqq_30: bool = False,
    prune_branches: Optional[Sequence[str]] = None,
) -> DecisionResult:
    """Decision tree with optional single-feature / prune modifications.

    Ablation defaults (when a signal is dropped):
    - SQQQ RSI: always take >= path (TECL)
    - UVXY RSI: skip UVXY high/extreme block → TQQQ SMA branch
    - QQQ SMA20: in extreme UVXY block always MAX_RSI
    - TQQQ SMA20: always MAX_RSI (skip SQQQ split)
    - QQQ RSI: skip bull UVXY-from-QQQ
    - SPY RSI: skip bull UVXY-from-SPY and bear SPXL
    """
    t = dict(thresholds or ROBUST_CORE_V1_THRESHOLDS)
    if unify_sqqq_30:
        t["sqqq_rsi_branch_1"] = 30
        t["sqqq_rsi_branch_2"] = 30

    qqq_ob = t.get("qqq_rsi_overbought", 80)
    spy_ob = t.get("spy_rsi_overbought", 80)
    tqqq_os = t.get("tqqq_rsi_oversold", 30)
    spy_os = t.get("spy_rsi_oversold", 30)
    uvxy_hi = t.get("uvxy_high", 70)
    uvxy_ext = t.get("uvxy_extreme", 80)
    sqqq_b1 = t.get("sqqq_rsi_branch_1", 30)
    sqqq_b2 = t.get("sqqq_rsi_branch_2", 30)
    prune = set(prune_branches or [])

    path: list[str] = []

    if state.price_spy > state.spy_sma_200:
        regime = "BULL"
        path.append("SPY > SPY_SMA200")
        if not drop_qqq_rsi and state.rsi_qqq > qqq_ob:
            path.append(f"QQQ_RSI > {qqq_ob}")
            d = DecisionResult("UVXY", regime, path, "B1", "BULL: QQQ_RSI -> UVXY")
            return _apply_prune(d, prune)
        if not drop_qqq_rsi:
            path.append(f"QQQ_RSI <= {qqq_ob}")
        if not drop_spy_rsi and state.rsi_spy > spy_ob:
            path.append(f"SPY_RSI > {spy_ob}")
            d = DecisionResult("UVXY", regime, path, "B2", "BULL: SPY_RSI -> UVXY")
            return _apply_prune(d, prune)
        if not drop_spy_rsi:
            path.append(f"SPY_RSI <= {spy_ob}")
        d = DecisionResult("TQQQ", regime, path, "B3", "BULL: default -> TQQQ")
        return _apply_prune(d, prune)

    regime = "BEAR"
    path.append("SPY <= SPY_SMA200")

    if state.rsi_tqqq < tqqq_os:
        path.append(f"TQQQ_RSI < {tqqq_os}")
        d = DecisionResult("TECL", regime, path, "B4", "BEAR: TQQQ_RSI oversold -> TECL")
        return _apply_prune(d, prune)
    path.append(f"TQQQ_RSI >= {tqqq_os}")

    if not drop_spy_rsi and state.rsi_spy < spy_os:
        path.append(f"SPY_RSI < {spy_os}")
        d = DecisionResult("SPXL", regime, path, "B5", "BEAR: SPY_RSI oversold -> SPXL")
        return _apply_prune(d, prune)
    if not drop_spy_rsi:
        path.append(f"SPY_RSI >= {spy_os}")

    if not drop_uvxy_rsi and state.rsi_uvxy > uvxy_hi:
        path.append(f"UVXY_RSI > {uvxy_hi}")
        if state.rsi_uvxy > uvxy_ext:
            path.append(f"UVXY_RSI > {uvxy_ext}")
            use_qqq_sma = not drop_qqq_sma and state.price_qqq > state.qqq_sma_20
            if drop_qqq_sma:
                path.append("QQQ_SMA20 DROPPED -> MAX_RSI")
                ticker, sub = get_max_rsi_asset(state.rsi_tecs, state.rsi_bsv)
                path.append(sub)
                bid = "B8" if ticker == "TECS" else "B9"
                d = DecisionResult(ticker, regime, path, bid, f"BEAR: extreme UVXY MAX_RSI -> {ticker}")
                return _apply_prune(d, prune)
            if use_qqq_sma:
                path.append("QQQ > QQQ_SMA20")
                if drop_sqqq_rsi:
                    path.append("SQQQ_RSI DROPPED -> TECL")
                    d = DecisionResult("TECL", regime, path, "B7", "BEAR: SQQQ dropped -> TECL")
                    return _apply_prune(d, prune)
                if state.rsi_sqqq < sqqq_b1:
                    path.append(f"SQQQ_RSI < {sqqq_b1}")
                    d = DecisionResult("TECS", regime, path, "B6", "BEAR: SQQQ low -> TECS")
                    return _apply_prune(d, prune)
                path.append(f"SQQQ_RSI >= {sqqq_b1}")
                d = DecisionResult("TECL", regime, path, "B7", "BEAR: SQQQ high -> TECL")
                return _apply_prune(d, prune)
            path.append("QQQ <= QQQ_SMA20")
            ticker, sub = get_max_rsi_asset(state.rsi_tecs, state.rsi_bsv)
            path.append(sub)
            bid = "B8" if ticker == "TECS" else "B9"
            d = DecisionResult(ticker, regime, path, bid, f"BEAR: MAX_RSI -> {ticker}")
            return _apply_prune(d, prune)
        path.append(f"UVXY_RSI <= {uvxy_ext}")
        d = DecisionResult("UVXY", regime, path, "B10", "BEAR: UVXY mid -> UVXY")
        return _apply_prune(d, prune)
    if not drop_uvxy_rsi:
        path.append(f"UVXY_RSI <= {uvxy_hi}")

    if drop_tqqq_sma:
        path.append("TQQQ_SMA20 DROPPED -> MAX_RSI")
        ticker, sub = get_max_rsi_asset(state.rsi_tecs, state.rsi_bsv)
        path.append(sub)
        bid = "B13" if ticker == "TECS" else "B14"
        d = DecisionResult(ticker, regime, path, bid, f"BEAR: no TQQQ SMA -> {ticker}")
        return _apply_prune(d, prune)

    if state.price_tqqq > state.tqqq_sma_20:
        path.append("TQQQ > TQQQ_SMA20")
        if drop_sqqq_rsi:
            path.append("SQQQ_RSI DROPPED -> TECL")
            d = DecisionResult("TECL", regime, path, "B12", "BEAR: SQQQ dropped -> TECL")
            return _apply_prune(d, prune)
        if state.rsi_sqqq < sqqq_b2:
            path.append(f"SQQQ_RSI < {sqqq_b2}")
            d = DecisionResult("TECS", regime, path, "B11", "BEAR: TQQQ>SMA SQQQ low -> TECS")
            return _apply_prune(d, prune)
        path.append(f"SQQQ_RSI >= {sqqq_b2}")
        d = DecisionResult("TECL", regime, path, "B12", "BEAR: TQQQ>SMA SQQQ high -> TECL")
        return _apply_prune(d, prune)

    path.append("TQQQ <= TQQQ_SMA20")
    ticker, sub = get_max_rsi_asset(state.rsi_tecs, state.rsi_bsv)
    path.append(sub)
    bid = "B13" if ticker == "TECS" else "B14"
    d = DecisionResult(ticker, regime, path, bid, f"BEAR: MAX_RSI -> {ticker}")
    return _apply_prune(d, prune)


def _apply_prune(d: DecisionResult, prune: set[str]) -> DecisionResult:
    if d.branch_id in prune:
        return DecisionResult(
            "BSV",
            d.regime,
            d.branch_path + [f"PRUNE_{d.branch_id}->BSV"],
            branch_id=f"{d.branch_id}_PRUNED",
            branch_rule=f"PRUNED {d.branch_id} -> BSV",
        )
    return d


def make_selector(**kwargs) -> Callable:
    def _fn(state: StrategyState, thresholds: dict) -> DecisionResult:
        # Prefer explicit thresholds passed by backtest; merge kwargs flags
        return select_target_options(state, thresholds, **kwargs)

    return _fn


def original_selector(state: StrategyState, thresholds: dict) -> DecisionResult:
    return select_target(state, thresholds)


def complexity_stats(
    *,
    n_params: int,
    n_thresholds: int,
    n_signal_assets: int,
    n_terminal_branches: int,
    cagr: float,
) -> dict:
    return {
        "number_of_parameters": n_params,
        "number_of_thresholds": n_thresholds,
        "number_of_signal_assets": n_signal_assets,
        "number_of_terminal_branches": n_terminal_branches,
        "performance_per_parameter": cagr / max(n_params + n_thresholds, 1),
        "performance_per_branch": cagr / max(n_terminal_branches, 1),
    }


ORIGINAL_COMPLEXITY = {
    "number_of_parameters": 4,
    "number_of_thresholds": 8,
    "number_of_signal_assets": 7,  # SPY,QQQ,TQQQ,SQQQ,UVXY,TECS,BSV
    "number_of_terminal_branches": 14,
}

STANDARDIZED_COMPLEXITY = dict(ORIGINAL_COMPLEXITY)  # same tree, round thresholds
