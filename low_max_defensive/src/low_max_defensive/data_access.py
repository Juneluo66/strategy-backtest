"""Load shared free cache + optional style ETFs (Yahoo only; no paid data)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from max_effect_vix.data import cache_path, load_benchmark, load_pilot
from max_effect_vix.universe_provider import load_historical_provider

from .config import FrozenConfig


def load_panels(config: FrozenConfig):
    opens, closes, volumes, vix = load_pilot(config.cache_dir)
    spy = load_benchmark(config.cache_dir, "SPY")
    provider = load_historical_provider(config.cache_dir)
    return opens, closes, volumes, vix, spy, provider


def ensure_style_etf(cache_dir: Path, symbol: str, start: str = "2010-01-01") -> Optional[pd.Series]:
    """Fetch/cache a style ETF if missing. Returns Adj Close; None on failure."""
    path = cache_path(cache_dir, symbol)
    if not path.exists():
        try:
            import yfinance as yf

            frame = yf.download(symbol, start=start, auto_adjust=False, progress=False, threads=False)
            if frame.empty:
                return None
            if isinstance(frame.columns, pd.MultiIndex):
                frame.columns = frame.columns.get_level_values(0)
            frame.index = pd.to_datetime(frame.index).tz_localize(None)
            frame.to_parquet(path)
        except Exception:
            return None
    frame = pd.read_parquet(path)
    column = "Adj Close" if "Adj Close" in frame.columns else "Close"
    series = frame[column].rename(symbol).sort_index()
    return series


def buy_and_hold_results(prices: pd.Series, name: str) -> pd.DataFrame:
    """Daily buy-and-hold returns from close-to-close (no rebalance costs)."""
    rets = prices.pct_change(fill_method=None).dropna()
    out = pd.DataFrame(
        {
            "gross_return": rets,
            "cost": 0.0,
            "net_return": rets,
            "exposure": 1.0,
        },
        index=rets.index,
    )
    out["equity"] = (1 + out["net_return"]).cumprod()
    out.attrs["label"] = name
    return out


def empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=["date", "turnover", "cost", "holdings", "reason"])
