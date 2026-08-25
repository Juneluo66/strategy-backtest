"""Yahoo Finance price cache for US ETFs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from .config import DualMomentumConfig


def cache_path(prices_dir: Path, symbol: str) -> Path:
    return prices_dir / f"{symbol.replace('-', '_')}.parquet"


def fetch_prices(
    config: DualMomentumConfig,
    *,
    refresh: bool = False,
    symbols: Optional[list[str]] = None,
) -> dict:
    """Download adjusted OHLCV; failures are recorded, never silently filled."""
    import yfinance as yf

    prices_dir = config.prices_dir
    prices_dir.mkdir(parents=True, exist_ok=True)
    requested = list(symbols or config.universe["fetch_symbols"])
    start = config.raw["data"]["start"]
    completed: list[str] = []
    failures: dict[str, str] = {}
    for symbol in requested:
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
        "source": config.raw["data"]["source"],
        "start": start,
        "requested_symbols": requested,
        "completed_symbols": completed,
        "failures": failures,
    }
    (config.cache_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_ohlc(config: DualMomentumConfig, symbols: Optional[list[str]] = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return Open and Close panels with consistent total-return adjustment.

    Yahoo `Open` is not dividend-adjusted when `Adj Close` is used naively.
    We scale Open by AdjClose/Close so overnight returns are coherent.
    """
    requested = list(symbols or config.universe["fetch_symbols"])
    opens: dict[str, pd.Series] = {}
    closes: dict[str, pd.Series] = {}
    missing: list[str] = []
    for symbol in requested:
        path = cache_path(config.prices_dir, symbol)
        if not path.exists():
            missing.append(symbol)
            continue
        frame = pd.read_parquet(path)
        frame.index = pd.to_datetime(frame.index).tz_localize(None)
        close = frame["Close"]
        adj = frame["Adj Close"] if "Adj Close" in frame.columns else close
        factor = (adj / close).replace([float("inf"), float("-inf")], pd.NA)
        adj_open = frame["Open"] * factor
        opens[symbol] = adj_open.rename(symbol)
        closes[symbol] = adj.rename(symbol)
    if missing:
        raise FileNotFoundError(f"missing cached prices for: {missing}; run fetch first")
    open_panel = pd.DataFrame(opens).sort_index()
    close_panel = pd.DataFrame(closes).sort_index()
    return open_panel, close_panel


def cash_symbol_on(date: pd.Timestamp, config: DualMomentumConfig, closes: pd.DataFrame) -> str:
    """Use SGOV when available; otherwise BIL proxy."""
    primary = config.raw["cash"]["primary"]
    proxy = config.raw["cash"]["proxy_before_primary"]
    if primary in closes.columns and pd.notna(closes.loc[date, primary]):
        # Prefer primary once it has a non-null history up to this date.
        history = closes[primary].loc[:date].dropna()
        if len(history) >= 5:
            return primary
    return proxy


def sgov_inception(closes: pd.DataFrame, primary: str = "SGOV") -> Optional[pd.Timestamp]:
    if primary not in closes.columns:
        return None
    series = closes[primary].dropna()
    if series.empty:
        return None
    return pd.Timestamp(series.index.min())


def audit_cache(config: DualMomentumConfig) -> dict:
    manifest_path = config.cache_dir / "manifest.json"
    if not manifest_path.exists():
        return {"status": "MISSING_CACHE", "manifest": None}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    coverage = {}
    for symbol in manifest.get("completed_symbols", []):
        path = cache_path(config.prices_dir, symbol)
        if not path.exists():
            coverage[symbol] = {"rows": 0, "start": None, "end": None}
            continue
        frame = pd.read_parquet(path)
        coverage[symbol] = {
            "rows": int(len(frame)),
            "start": str(frame.index.min().date()) if len(frame) else None,
            "end": str(frame.index.max().date()) if len(frame) else None,
        }
    return {"status": "OK" if not manifest.get("failures") else "PARTIAL", "manifest": manifest, "coverage": coverage}
