"""Performance calculations for periodic portfolio returns."""
from __future__ import annotations

import numpy as np
import pandas as pd


def performance_metrics(returns: pd.Series, periods_per_year: float = 12.0) -> dict[str, float]:
    values = pd.to_numeric(returns, errors="coerce").dropna().to_numpy(dtype=float)
    if len(values) == 0:
        return {key: np.nan for key in ("annual_return", "annual_volatility", "sharpe", "sortino", "calmar", "max_drawdown", "total_return", "win_rate", "best_period", "worst_period")}
    nav = np.cumprod(1.0 + values)
    annual_return = float(nav[-1] ** (periods_per_year / len(values)) - 1.0)
    annual_volatility = float(np.std(values, ddof=1) * np.sqrt(periods_per_year)) if len(values) > 1 else np.nan
    sharpe = annual_return / annual_volatility if annual_volatility and annual_volatility > 1e-12 else np.nan
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    downside = values[values < 0]
    downside_volatility = float(np.std(downside, ddof=1) * np.sqrt(periods_per_year)) if len(downside) > 1 else np.nan
    sortino = annual_return / downside_volatility if downside_volatility and downside_volatility > 1e-12 else np.nan
    max_drawdown = float(drawdown.min())
    return {
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "calmar": annual_return / abs(max_drawdown) if max_drawdown < -1e-12 else np.nan,
        "max_drawdown": max_drawdown,
        "total_return": float(nav[-1] - 1.0),
        "win_rate": float((values > 0).mean()),
        "best_period": float(values.max()),
        "worst_period": float(values.min()),
    }


def relative_metrics(strategy: pd.Series, benchmark: pd.Series, periods_per_year: float = 12.0) -> dict[str, float]:
    """Compute aligned excess-return, regression, and capture statistics."""
    frame = pd.concat([pd.Series(strategy), pd.Series(benchmark)], axis=1).dropna()
    if len(frame) < 3:
        return {key: np.nan for key in ("excess_annual_return", "tracking_error", "information_ratio", "beta", "alpha", "up_capture", "down_capture")}
    s, b = frame.iloc[:, 0].to_numpy(float), frame.iloc[:, 1].to_numpy(float)
    excess = s - b
    tracking_error = float(np.std(excess, ddof=1) * np.sqrt(periods_per_year))
    information_ratio = float(excess.mean() * periods_per_year / tracking_error) if tracking_error > 1e-12 else np.nan
    beta = float(np.cov(s, b, ddof=1)[0, 1] / np.var(b, ddof=1)) if np.var(b, ddof=1) > 1e-12 else np.nan
    alpha = float((s.mean() - beta * b.mean()) * periods_per_year) if np.isfinite(beta) else np.nan
    up = b > 0
    down = b < 0
    return {
        "excess_annual_return": float(np.prod(1 + s) ** (periods_per_year / len(s)) / np.prod(1 + b) ** (periods_per_year / len(b)) - 1),
        "tracking_error": tracking_error,
        "information_ratio": information_ratio,
        "beta": beta,
        "alpha": alpha,
        "up_capture": float(s[up].mean() / b[up].mean()) if up.any() and abs(b[up].mean()) > 1e-12 else np.nan,
        "down_capture": float(s[down].mean() / b[down].mean()) if down.any() and abs(b[down].mean()) > 1e-12 else np.nan,
    }


def drawdown_table(returns: pd.Series) -> pd.DataFrame:
    """Summarize non-overlapping drawdown episodes."""
    indexed = pd.Series(returns).dropna()
    nav = (1 + indexed).cumprod()
    peak = nav.cummax()
    drawdown = nav / peak - 1
    episodes, active = [], None
    for date, value in drawdown.items():
        if value < 0 and active is None:
            active = {"start": date, "trough": date, "max_drawdown": value}
        if active is not None and value < active["max_drawdown"]:
            active.update(trough=date, max_drawdown=value)
        if active is not None and value >= -1e-12:
            active["recovery"] = date
            active["duration_periods"] = len(indexed.loc[active["start"]:date])
            episodes.append(active)
            active = None
    if active is not None:
        active["recovery"] = pd.NaT
        active["duration_periods"] = len(indexed.loc[active["start"]:])
        episodes.append(active)
    return pd.DataFrame(episodes).sort_values("max_drawdown") if episodes else pd.DataFrame()


def yearly_returns(dated_returns: pd.Series) -> pd.DataFrame:
    """Compound monthly returns into calendar-year returns."""
    values = pd.Series(dated_returns).dropna()
    values.index = pd.to_datetime(values.index)
    yearly = values.groupby(values.index.year).apply(lambda items: (1 + items).prod() - 1)
    return yearly.rename("return").rename_axis("year").reset_index()


def rolling_metrics(dated_returns: pd.Series, window: int = 12) -> pd.DataFrame:
    """Return rolling annualized return, volatility, and Sharpe."""
    values = pd.Series(dated_returns).dropna()
    annual_return = (1 + values).rolling(window).apply(lambda x: x.prod() ** (12 / len(x)) - 1, raw=False)
    volatility = values.rolling(window).std(ddof=1) * np.sqrt(12)
    return pd.DataFrame(
        {"date": pd.to_datetime(values.index), "window_months": window, "annual_return": annual_return, "annual_volatility": volatility}
    ).assign(sharpe=lambda frame: frame["annual_return"] / frame["annual_volatility"])
