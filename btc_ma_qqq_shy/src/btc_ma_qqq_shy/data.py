"""Yahoo Finance Adj Close cache."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import ProjectConfig


def cache_path(prices_dir: Path, symbol: str) -> Path:
    return prices_dir / f"{symbol.replace('-', '_').replace('^', '')}.parquet"


def fetch_prices(config: ProjectConfig, *, refresh: bool = False) -> dict:
    import yfinance as yf

    prices_dir = config.prices_dir
    prices_dir.mkdir(parents=True, exist_ok=True)
    start = config.raw["data"]["start"]
    completed: list[str] = []
    failures: dict[str, str] = {}
    actions: dict[str, str] = {}

    for symbol in config.symbols:
        path = cache_path(prices_dir, symbol)
        if path.exists() and not refresh:
            completed.append(symbol)
            actions[symbol] = "cache_hit"
            continue
        try:
            frame = yf.download(
                symbol, start=start, auto_adjust=False, progress=False, threads=False
            )
            if frame.empty:
                raise ValueError("empty response")
            if isinstance(frame.columns, pd.MultiIndex):
                frame.columns = frame.columns.get_level_values(0)
            frame = frame.rename_axis("date").reset_index()
            frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
            frame = frame.set_index("date").sort_index()
            keep = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in frame.columns]
            frame[keep].to_parquet(path)
            completed.append(symbol)
            actions[symbol] = "downloaded"
        except Exception as exc:  # noqa: BLE001 — surface per-symbol failure
            failures[symbol] = str(exc)
            actions[symbol] = "failed"

    return {"completed": completed, "failures": failures, "actions": actions}


def load_adj_close(config: ProjectConfig) -> pd.DataFrame:
    cols = {}
    for symbol in config.symbols:
        path = cache_path(config.prices_dir, symbol)
        if not path.exists():
            raise FileNotFoundError(f"missing cache for {symbol}: {path}")
        frame = pd.read_parquet(path)
        if "Adj Close" not in frame.columns:
            raise KeyError(f"{symbol} missing Adj Close")
        s = frame["Adj Close"].astype(float)
        s.index = pd.to_datetime(s.index).tz_localize(None)
        cols[symbol] = s
    out = pd.DataFrame(cols).sort_index()
    return out
