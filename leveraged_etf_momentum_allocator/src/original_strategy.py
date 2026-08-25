"""Exact decision tree from QuantConnect ConditionalSectorRotation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from config import ProjectConfig


@dataclass(frozen=True)
class StrategyState:
    price_spy: float
    price_qqq: float
    price_tqqq: float
    spy_sma_200: float
    qqq_sma_20: float
    tqqq_sma_20: float
    rsi_qqq: float
    rsi_spy: float
    rsi_tqqq: float
    rsi_sqqq: float
    rsi_uvxy: float
    rsi_tecs: float
    rsi_bsv: float


@dataclass
class DecisionResult:
    target: str
    regime: str  # BULL or BEAR
    branch_path: list[str] = field(default_factory=list)
    branch_id: str = ""
    branch_rule: str = ""


# Terminal branch catalog — fixed IDs for attribution
TERMINAL_BRANCHES: dict[str, str] = {
    "B1": "BULL: QQQ_RSI > 81 -> UVXY",
    "B2": "BULL: SPY_RSI > 80 (QQQ_RSI<=81) -> UVXY",
    "B3": "BULL: default -> TQQQ",
    "B4": "BEAR: TQQQ_RSI < 30 -> TECL",
    "B5": "BEAR: SPY_RSI < 30 -> SPXL",
    "B6": "BEAR: UVXY>74, UVXY>84, QQQ>SMA20, SQQQ<31 -> TECS",
    "B7": "BEAR: UVXY>74, UVXY>84, QQQ>SMA20, SQQQ>=31 -> TECL",
    "B8": "BEAR: UVXY>74, UVXY>84, QQQ<=SMA20, MAX_RSI -> TECS",
    "B9": "BEAR: UVXY>74, UVXY>84, QQQ<=SMA20, MAX_RSI -> BSV",
    "B10": "BEAR: UVXY>74, UVXY<=84 -> UVXY",
    "B11": "BEAR: TQQQ>SMA20, SQQQ<34 -> TECS",
    "B12": "BEAR: TQQQ>SMA20, SQQQ>=34 -> TECL",
    "B13": "BEAR: TQQQ<=SMA20, MAX_RSI -> TECS",
    "B14": "BEAR: TQQQ<=SMA20, MAX_RSI -> BSV",
}


def _finalize(decision: DecisionResult) -> DecisionResult:
    """Attach branch_id and branch_rule from target + path."""
    path = decision.branch_path
    target = decision.target
    regime = decision.regime
    bid = ""
    if regime == "BULL":
        if target == "UVXY" and len(path) >= 2 and path[1].startswith("QQQ_RSI >"):
            bid = "B1"
        elif target == "UVXY":
            bid = "B2"
        else:
            bid = "B3"
    else:
        if target == "TECL" and any("TQQQ_RSI <" in p for p in path):
            bid = "B4"
        elif target == "SPXL":
            bid = "B5"
        elif target == "TECS" and any("UVXY_RSI >" in p for p in path) and any("QQQ >" in p for p in path):
            bid = "B6"
        elif target == "TECL" and any("UVXY_RSI >" in p for p in path) and any("QQQ >" in p for p in path):
            bid = "B7"
        elif target == "TECS" and "MAX_RSI" in " ".join(path):
            bid = "B8"
        elif target == "BSV" and "MAX_RSI" in " ".join(path):
            bid = "B9"
        elif target == "UVXY":
            bid = "B10"
        elif target == "TECS" and any("TQQQ >" in p for p in path):
            bid = "B11"
        elif target == "TECL" and any("TQQQ >" in p for p in path):
            bid = "B12"
        elif target == "TECS":
            bid = "B13"
        elif target == "BSV":
            bid = "B14"
        else:
            bid = f"BX_{target}"
    rule = TERMINAL_BRANCHES.get(bid, " → ".join(path))
    decision.branch_id = bid
    decision.branch_rule = rule
    return decision


def get_max_rsi_asset(rsi_tecs: float, rsi_bsv: float) -> tuple[str, str]:
    """GetMaxRsiAsset(['TECS', 'BSV']) — strict >; TECS wins ties (QC iteration order)."""
    best_ticker = "TECS"
    highest_rsi = rsi_tecs
    if rsi_bsv > highest_rsi:
        highest_rsi = rsi_bsv
        best_ticker = "BSV"
    return best_ticker, f"MAX_RSI(TECS,BSV)->{best_ticker}"


def select_target(state: StrategyState, thresholds: Optional[dict] = None) -> DecisionResult:
    """Deterministic decision tree — strict > and < only (no >=/<=)."""
    t = thresholds or {}
    qqq_ob = t.get("qqq_rsi_overbought", 81)
    spy_ob = t.get("spy_rsi_overbought", 80)
    tqqq_os = t.get("tqqq_rsi_oversold", 30)
    spy_os = t.get("spy_rsi_oversold", 30)
    uvxy_hi = t.get("uvxy_high", 74)
    uvxy_ext = t.get("uvxy_extreme", 84)
    sqqq_b1 = t.get("sqqq_rsi_branch_1", 31)
    sqqq_b2 = t.get("sqqq_rsi_branch_2", 34)

    path: list[str] = []

    if state.price_spy > state.spy_sma_200:
        regime = "BULL"
        path.append("SPY > SPY_SMA200")
        if state.rsi_qqq > qqq_ob:
            path.append(f"QQQ_RSI > {qqq_ob}")
            return _finalize(DecisionResult("UVXY", regime, path))
        path.append(f"QQQ_RSI <= {qqq_ob}")
        if state.rsi_spy > spy_ob:
            path.append(f"SPY_RSI > {spy_ob}")
            return _finalize(DecisionResult("UVXY", regime, path))
        path.append(f"SPY_RSI <= {spy_ob}")
        return _finalize(DecisionResult("TQQQ", regime, path))

    regime = "BEAR"
    path.append("SPY <= SPY_SMA200")

    if state.rsi_tqqq < tqqq_os:
        path.append(f"TQQQ_RSI < {tqqq_os}")
        return _finalize(DecisionResult("TECL", regime, path))
    path.append(f"TQQQ_RSI >= {tqqq_os}")

    if state.rsi_spy < spy_os:
        path.append(f"SPY_RSI < {spy_os}")
        return _finalize(DecisionResult("SPXL", regime, path))
    path.append(f"SPY_RSI >= {spy_os}")

    if state.rsi_uvxy > uvxy_hi:
        path.append(f"UVXY_RSI > {uvxy_hi}")
        if state.rsi_uvxy > uvxy_ext:
            path.append(f"UVXY_RSI > {uvxy_ext}")
            if state.price_qqq > state.qqq_sma_20:
                path.append("QQQ > QQQ_SMA20")
                if state.rsi_sqqq < sqqq_b1:
                    path.append(f"SQQQ_RSI < {sqqq_b1}")
                    return _finalize(DecisionResult("TECS", regime, path))
                path.append(f"SQQQ_RSI >= {sqqq_b1}")
                return _finalize(DecisionResult("TECL", regime, path))
            path.append("QQQ <= QQQ_SMA20")
            ticker, sub = get_max_rsi_asset(state.rsi_tecs, state.rsi_bsv)
            path.append(sub)
            return _finalize(DecisionResult(ticker, regime, path))
        path.append(f"UVXY_RSI <= {uvxy_ext}")
        return _finalize(DecisionResult("UVXY", regime, path))
    path.append(f"UVXY_RSI <= {uvxy_hi}")

    if state.price_tqqq > state.tqqq_sma_20:
        path.append("TQQQ > TQQQ_SMA20")
        if state.rsi_sqqq < sqqq_b2:
            path.append(f"SQQQ_RSI < {sqqq_b2}")
            return _finalize(DecisionResult("TECS", regime, path))
        path.append(f"SQQQ_RSI >= {sqqq_b2}")
        return _finalize(DecisionResult("TECL", regime, path))
    path.append("TQQQ <= TQQQ_SMA20")
    ticker, sub = get_max_rsi_asset(state.rsi_tecs, state.rsi_bsv)
    path.append(sub)
    return _finalize(DecisionResult(ticker, regime, path))


def state_from_row(
    date,
    closes: "pd.DataFrame",
    rsi: "pd.DataFrame",
    sma: dict,
) -> StrategyState:
    import pandas as pd

    return StrategyState(
        price_spy=float(closes.loc[date, "SPY"]),
        price_qqq=float(closes.loc[date, "QQQ"]),
        price_tqqq=float(closes.loc[date, "TQQQ"]),
        spy_sma_200=float(sma["SPY_SMA200"].loc[date]),
        qqq_sma_20=float(sma["QQQ_SMA20"].loc[date]),
        tqqq_sma_20=float(sma["TQQQ_SMA20"].loc[date]),
        rsi_qqq=float(rsi.loc[date, "QQQ"]),
        rsi_spy=float(rsi.loc[date, "SPY"]),
        rsi_tqqq=float(rsi.loc[date, "TQQQ"]),
        rsi_sqqq=float(rsi.loc[date, "SQQQ"]),
        rsi_uvxy=float(rsi.loc[date, "UVXY"]),
        rsi_tecs=float(rsi.loc[date, "TECS"]),
        rsi_bsv=float(rsi.loc[date, "BSV"]),
    )


def load_thresholds(cfg: ProjectConfig) -> dict:
    return dict(cfg.original.get("thresholds", {}))
