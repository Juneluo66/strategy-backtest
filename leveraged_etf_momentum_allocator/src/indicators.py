"""Technical indicators matching QuantConnect semantics (Wilder RSI, simple SMA)."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def simple_sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average — equivalent to QC SMA with simple type."""
    return series.rolling(window=period, min_periods=period).mean()


def wilder_rsi(close: pd.Series, period: int = 10) -> pd.Series:
    """Wilder (RMA) RSI — matches QuantConnect MovingAverageType.Wilders."""
    n = len(close)
    if n < period + 1:
        return pd.Series(np.nan, index=close.index)

    delta = close.diff()
    gain = delta.clip(lower=0.0).to_numpy(dtype=float, copy=False)
    loss = (-delta).clip(lower=0.0).to_numpy(dtype=float, copy=False)

    avg_gain = np.full(n, np.nan)
    avg_loss = np.full(n, np.nan)
    avg_gain[period] = gain[1 : period + 1].mean()
    avg_loss[period] = loss[1 : period + 1].mean()

    # Vectorized recurrence on numpy arrays (faster than pandas iloc loop).
    for i in range(period + 1, n):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period

    rs = avg_gain / np.where(avg_loss == 0, np.nan, avg_loss)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = np.where((avg_loss == 0) & (avg_gain > 0), 100.0, rsi)
    rsi = np.where((avg_gain == 0) & (avg_loss > 0), 0.0, rsi)
    return pd.Series(rsi, index=close.index)


def build_indicator_panels(
    closes: pd.DataFrame,
    *,
    rsi_period: int = 10,
    spy_sma_period: int = 200,
    qqq_sma_period: int = 20,
    tqqq_sma_period: int = 20,
    universe: list[str],
) -> dict[str, pd.DataFrame]:
    """Build RSI/SMA on each ticker's contiguous history, then align to shared calendar."""
    rsi_panels: dict[str, pd.Series] = {}
    for ticker in universe:
        if ticker not in closes.columns:
            continue
        series = closes[ticker].dropna()
        if series.empty:
            continue
        rsi_panels[ticker] = wilder_rsi(series, rsi_period).reindex(closes.index)

    def _sma_aligned(col: str, period: int) -> Optional[pd.Series]:
        if col not in closes.columns:
            return None
        s = closes[col].dropna()
        return simple_sma(s, period).reindex(closes.index)

    sma = {
        "SPY_SMA200": _sma_aligned("SPY", spy_sma_period),
        "QQQ_SMA20": _sma_aligned("QQQ", qqq_sma_period),
        "TQQQ_SMA20": _sma_aligned("TQQQ", tqqq_sma_period),
    }
    return {"rsi": pd.DataFrame(rsi_panels), "sma": sma}


def indicators_ready(
    date: pd.Timestamp,
    closes: pd.DataFrame,
    indicators: dict,
    universe: list[str],
    *,
    rsi_period: int,
    spy_sma_period: int,
    warmup_bars: int,
) -> bool:
    """True when all required indicators have valid values (post warm-up)."""
    cal = closes.index
    pos = cal.get_loc(date)
    if isinstance(pos, slice):
        pos = pos.start or 0
    if pos < warmup_bars:
        return False
    rsi_df = indicators["rsi"]
    for ticker in universe:
        if ticker not in closes.columns:
            return False
        if pd.isna(closes.loc[date, ticker]):
            return False
        val = rsi_df.loc[date, ticker]
        if pd.isna(val):
            return False
    for key, period in [("SPY_SMA200", spy_sma_period), ("QQQ_SMA20", 20), ("TQQQ_SMA20", 20)]:
        sma = indicators["sma"].get(key)
        if sma is None or pd.isna(sma.loc[date]):
            return False
    return True
