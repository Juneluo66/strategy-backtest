"""Simple baseline target selectors — same execution as ORIGINAL."""
from __future__ import annotations

from original_strategy import DecisionResult, StrategyState, load_thresholds, select_target


def always_target(ticker: str) -> callable:
    def _fn(state: StrategyState, thresholds: dict) -> DecisionResult:
        return DecisionResult(ticker, "BASELINE", [f"ALWAYS_{ticker}"])
    return _fn


def spy_sma200_tqqq_bsv(state: StrategyState, thresholds: dict) -> DecisionResult:
    if state.price_spy > state.spy_sma_200:
        return DecisionResult("TQQQ", "BULL", ["SPY > SMA200", "TQQQ"])
    return DecisionResult("BSV", "BEAR", ["SPY <= SMA200", "BSV"])


def spy_sma200_tqqq_cash(state: StrategyState, thresholds: dict) -> DecisionResult:
    if state.price_spy > state.spy_sma_200:
        return DecisionResult("TQQQ", "BULL", ["SPY > SMA200", "TQQQ"])
    return DecisionResult("CASH", "BEAR", ["SPY <= SMA200", "CASH"])


def original_bull_bsv_bear(state: StrategyState, thresholds: dict) -> DecisionResult:
    t = thresholds
    if state.price_spy > state.spy_sma_200:
        path = ["SPY > SMA200"]
        if state.rsi_qqq > t.get("qqq_rsi_overbought", 81):
            path.append("QQQ_RSI > 81")
            return DecisionResult("UVXY", "BULL", path)
        if state.rsi_spy > t.get("spy_rsi_overbought", 80):
            path.append("SPY_RSI > 80")
            return DecisionResult("UVXY", "BULL", path)
        path.append("TQQQ")
        return DecisionResult("TQQQ", "BULL", path)
    return DecisionResult("BSV", "BEAR", ["SPY <= SMA200", "BSV"])


def original_bull_cash_bear(state: StrategyState, thresholds: dict) -> DecisionResult:
    t = thresholds
    if state.price_spy > state.spy_sma_200:
        path = ["SPY > SMA200"]
        if state.rsi_qqq > t.get("qqq_rsi_overbought", 81):
            path.append("QQQ_RSI > 81")
            return DecisionResult("UVXY", "BULL", path)
        if state.rsi_spy > t.get("spy_rsi_overbought", 80):
            path.append("SPY_RSI > 80")
            return DecisionResult("UVXY", "BULL", path)
        path.append("TQQQ")
        return DecisionResult("TQQQ", "BULL", path)
    return DecisionResult("CASH", "BEAR", ["SPY <= SMA200", "CASH"])


def bull_always_tqqq(state: StrategyState, thresholds: dict) -> DecisionResult:
    if state.price_spy > state.spy_sma_200:
        return DecisionResult("TQQQ", "BULL", ["SPY > SMA200", "ALWAYS_TQQQ"])
    return select_target(state, thresholds)


def original_no_uvxy(state: StrategyState, thresholds: dict) -> DecisionResult:
    """ORIGINAL but UVXY branches -> BSV."""
    d = select_target(state, thresholds)
    if d.target == "UVXY":
        return DecisionResult("BSV", d.regime, d.branch_path + ["UVXY->BSV_PROXY"])
    return d


BASELINE_REGISTRY = {
    "TQQQ_BUY_HOLD": always_target("TQQQ"),
    "SPY_SMA200_TQQQ_BSV": spy_sma200_tqqq_bsv,
    "SPY_SMA200_TQQQ_CASH": spy_sma200_tqqq_cash,
    "ORIGINAL_BULL_BSV_BEAR": original_bull_bsv_bear,
    "ORIGINAL_BULL_CASH_BEAR": original_bull_cash_bear,
    "BULL_ALWAYS_TQQQ": bull_always_tqqq,
    "ORIGINAL_NO_UVXY": original_no_uvxy,
}

STANDARDIZED_THRESHOLDS = {
    "qqq_rsi_overbought": 80,
    "spy_rsi_overbought": 80,
    "tqqq_rsi_oversold": 30,
    "spy_rsi_oversold": 30,
    "uvxy_high": 70,
    "uvxy_extreme": 80,
    "sqqq_rsi_branch_1": 30,
    "sqqq_rsi_branch_2": 30,
}

LONG_DELEVERAGED_MAP = {
    "TQQQ": "QQQ",
    "SPXL": "SPY",
    "TECL": "XLK",
}

RISK_REDUCED_MAP = {
    "TQQQ": "QQQ",
    "SPXL": "SPY",
    "TECL": "XLK",
    "TECS": "BSV",
    "UVXY": "BSV",
}

BRANCH_SENSITIVITY_THRESHOLDS = {
    "uvxy_high_70": {"uvxy_high": 70},
    "uvxy_extreme_80": {"uvxy_extreme": 80},
    "sqqq_b1_30": {"sqqq_rsi_branch_1": 30},
    "sqqq_b2_30": {"sqqq_rsi_branch_2": 30},
    "combined_nonstandard": {
        "uvxy_high": 70,
        "uvxy_extreme": 80,
        "sqqq_rsi_branch_1": 30,
        "sqqq_rsi_branch_2": 30,
    },
}
