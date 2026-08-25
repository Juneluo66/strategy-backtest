"""Point-in-time price-based controls for free-data exploratory variants."""
from __future__ import annotations

import numpy as np
import pandas as pd


def winsorize(series: pd.Series, limits: tuple[float, float] = (0.025, 0.975)) -> pd.Series:
    valid = series.dropna()
    if len(valid) < 5:
        return series
    return series.clip(valid.quantile(limits[0]), valid.quantile(limits[1]))


def rolling_volatility(returns: pd.DataFrame, lookback: int = 63) -> pd.DataFrame:
    return returns.rolling(lookback, min_periods=lookback).std()


def rolling_beta(
    returns: pd.DataFrame, benchmark_returns: pd.Series, lookback: int = 252, min_observations: int = 126
) -> pd.DataFrame:
    benchmark_var = benchmark_returns.rolling(lookback, min_periods=min_observations).var()
    return returns.rolling(lookback, min_periods=min_observations).cov(benchmark_returns).div(
        benchmark_var, axis=0
    )


def residualize(factor: pd.Series, control: pd.Series, limits: tuple[float, float]) -> pd.Series:
    """Cross-sectional OLS residual with no current/future information beyond inputs."""
    frame = pd.concat({"factor": factor, "control": control}, axis=1).dropna()
    if len(frame) < 10 or frame["control"].nunique() < 2:
        return pd.Series(index=factor.index, dtype=float)
    x = winsorize(frame["control"], limits)
    y = winsorize(frame["factor"], limits)
    design = np.column_stack([np.ones(len(frame)), x.to_numpy()])
    residual = y.to_numpy() - design @ np.linalg.lstsq(design, y.to_numpy(), rcond=None)[0]
    result = pd.Series(index=factor.index, dtype=float)
    result.loc[frame.index] = residual
    return result


def controlled_factor(
    factor: pd.Series, volatility: pd.Series, beta: pd.Series, variant: str, limits: tuple[float, float]
) -> pd.Series:
    if variant == "raw":
        return factor
    if variant == "vol_neutral":
        return residualize(factor, volatility, limits)
    if variant == "beta_neutral":
        return residualize(factor, beta, limits)
    if variant == "size_neutral":
        raise RuntimeError("BLOCKED_BY_PIT_MARKET_CAP")
    raise ValueError(f"unsupported factor variant: {variant}")
