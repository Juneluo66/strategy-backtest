"""Cross-sectional selection rules."""
from __future__ import annotations

import math

import pandas as pd


def select_low_max(
    factor_by_symbol: pd.Series, portfolio_decile: float = 0.10, max_portfolio_size: int = 25
) -> list[str]:
    """Select low-MAX decile, capped at the research portfolio size."""
    valid = factor_by_symbol.dropna().sort_values(kind="stable")
    count = min(max_portfolio_size, math.floor(len(valid) * portfolio_decile))
    return valid.index[:count].tolist() if count else []


def select_high_max(
    factor_by_symbol: pd.Series, portfolio_decile: float = 0.10, max_portfolio_size: int = 25
) -> list[str]:
    """Select high-MAX decile for the short-leg diagnostic (same size rule as long)."""
    valid = factor_by_symbol.dropna().sort_values(kind="stable", ascending=False)
    count = min(max_portfolio_size, math.floor(len(valid) * portfolio_decile))
    return valid.index[:count].tolist() if count else []


def equal_weights(symbols: list[str], leverage: float) -> pd.Series:
    if not symbols:
        return pd.Series(dtype=float, name="target_weight")
    return pd.Series(leverage / len(symbols), index=symbols, name="target_weight")
