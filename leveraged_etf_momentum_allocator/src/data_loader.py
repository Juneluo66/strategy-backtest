"""Daily OHLCV loading — compatible with sibling strategy-backtest projects."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from config import ProjectConfig

REQUIRED_COLUMNS = ("date", "ticker", "open", "high", "low", "close", "adj_close", "volume")


def cache_path(prices_dir: Path, symbol: str) -> Path:
    return prices_dir / f"{symbol.replace('-', '_')}.parquet"


def fetch_prices(
    config: ProjectConfig,
    *,
    symbols: list[str],
    start: str = "2010-01-01",
    refresh: bool = False,
) -> dict:
    """Download adjusted OHLCV via yfinance; failures recorded, never silently filled."""
    import yfinance as yf

    prices_dir = config.cache_dir
    prices_dir.mkdir(parents=True, exist_ok=True)
    completed: list[str] = []
    failures: dict[str, str] = {}
    for symbol in symbols:
        path = cache_path(prices_dir, symbol)
        if path.exists() and not refresh:
            completed.append(symbol)
            continue
        try:
            frame = yf.download(
                symbol, start=start, auto_adjust=False, progress=False, threads=False
            )
            if frame.empty:
                raise ValueError("empty response")
            if isinstance(frame.columns, pd.MultiIndex):
                frame.columns = frame.columns.get_level_values(0)
            frame.index = pd.to_datetime(frame.index).tz_localize(None)
            frame.to_parquet(path)
            completed.append(symbol)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failures[symbol] = str(exc)
    manifest = {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "yahoo_finance_adj_close",
        "start": start,
        "requested_symbols": symbols,
        "completed_symbols": completed,
        "failures": failures,
    }
    manifest_path = config.cache_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _parquet_to_long(path: Path, symbol: str) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    close = frame["Close"]
    adj = frame["Adj Close"] if "Adj Close" in frame.columns else close
    factor = (adj / close).replace([np.inf, -np.inf], pd.NA).fillna(1.0)
    adj_open = frame["Open"] * factor
    out = pd.DataFrame(
        {
            "date": frame.index,
            "ticker": symbol,
            "open": adj_open.values,
            "high": frame["High"].values,
            "low": frame["Low"].values,
            "close": close.values,
            "adj_close": adj.values,
            "volume": frame["Volume"].values if "Volume" in frame.columns else np.nan,
        }
    )
    return out


def load_long_frame(
    config: ProjectConfig,
    symbols: list[str],
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """Load long-format OHLCV; no forward-fill before inception."""
    missing: list[str] = []
    frames: list[pd.DataFrame] = []
    for symbol in symbols:
        path = cache_path(config.cache_dir, symbol)
        if not path.exists():
            missing.append(symbol)
            continue
        frames.append(_parquet_to_long(path, symbol))
    if missing:
        raise FileNotFoundError(f"missing cached prices for: {missing}")
    long = pd.concat(frames, ignore_index=True).sort_values(["date", "ticker"])
    if start:
        long = long.loc[long["date"] >= pd.Timestamp(start)]
    if end:
        long = long.loc[long["date"] <= pd.Timestamp(end)]
    return long.reset_index(drop=True)


def load_panels(
    config: ProjectConfig,
    symbols: list[str],
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    """Return (adj_open_panel, adj_close_panel, shared_calendar)."""
    long = load_long_frame(config, symbols, start=start, end=end)
    opens = long.pivot(index="date", columns="ticker", values="open").sort_index()
    closes = long.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    calendar = pd.DatetimeIndex(opens.index.intersection(closes.index).sort_values())
    return opens.reindex(calendar), closes.reindex(calendar), calendar


def inception_date(closes: pd.DataFrame, ticker: str) -> Optional[pd.Timestamp]:
    if ticker not in closes.columns:
        return None
    series = closes[ticker].dropna()
    if series.empty:
        return None
    return pd.Timestamp(series.index.min())


def tradable_universe_on(
    closes: pd.DataFrame,
    tickers: list[str],
    as_of: pd.Timestamp,
) -> list[str]:
    """Return tickers with valid adj_close on as_of — no forward-fill."""
    available: list[str] = []
    for ticker in tickers:
        if ticker not in closes.columns:
            continue
        if as_of not in closes.index:
            continue
        if pd.notna(closes.loc[as_of, ticker]):
            available.append(ticker)
    return available


def audit_cache(config: ProjectConfig) -> dict:
    manifest_path = config.cache_dir / "manifest.json"
    if not manifest_path.exists():
        return {"status": "MISSING_CACHE", "manifest": None}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    coverage = {}
    for symbol in manifest.get("completed_symbols", []):
        path = cache_path(config.cache_dir, symbol)
        if not path.exists():
            coverage[symbol] = {"rows": 0, "start": None, "end": None}
            continue
        frame = pd.read_parquet(path)
        coverage[symbol] = {
            "rows": int(len(frame)),
            "start": str(frame.index.min().date()) if len(frame) else None,
            "end": str(frame.index.max().date()) if len(frame) else None,
        }
    return {
        "status": "OK" if not manifest.get("failures") else "PARTIAL",
        "manifest": manifest,
        "coverage": coverage,
    }
