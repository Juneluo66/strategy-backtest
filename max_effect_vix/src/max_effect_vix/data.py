"""Free-data cache with an explicitly non-PIT current-constituent universe."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Optional

import pandas as pd

PILOT_SYMBOLS = [
    "AAPL", "ABBV", "ABT", "ADBE", "AMD", "AMGN", "AMZN", "AVGO", "BAC", "BKNG",
    "BRK-B", "CAT", "CMCSA", "COST", "CRM", "CSCO", "CVX", "DIS", "GOOG", "GS",
    "HD", "HON", "IBM", "INTC", "JNJ", "JPM", "KO", "LIN", "LLY", "MA", "MCD",
    "META", "MMM", "MRK", "MSFT", "NFLX", "NKE", "NVDA", "ORCL", "PEP", "PFE",
    "PG", "PM", "QCOM", "TMO", "TSLA", "UNH", "V", "WMT", "XOM",
]


def _safe_name(symbol: str) -> str:
    return symbol.replace("^", "index_").replace("-", "_")


def cache_path(cache_dir: Path, symbol: str) -> Path:
    return cache_dir / f"{_safe_name(symbol)}.parquet"


def fetch_current_sp500_universe(cache_dir: Path) -> list[str]:
    """Cache today's S&P 500 membership; it is never represented as historical membership."""
    import requests

    response = requests.get(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        headers={"User-Agent": "Mozilla/5.0 (research; max-effect-vix)"},
        timeout=30,
    )
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text))
    table = next(frame for frame in tables if "Symbol" in frame.columns)
    symbols = sorted(table["Symbol"].astype(str).str.replace(".", "-", regex=False).unique().tolist())
    payload = {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Wikipedia current S&P 500 constituents",
        "status": "SURVIVORSHIP_BIASED_PILOT",
        "symbols": symbols,
    }
    (cache_dir / "universe_snapshot.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return symbols


def current_universe(cache_dir: Path, fallback_limit: int) -> list[str]:
    snapshot = cache_dir / "universe_snapshot.json"
    if snapshot.exists():
        return json.loads(snapshot.read_text(encoding="utf-8"))["symbols"]
    return PILOT_SYMBOLS[:fallback_limit]


def fetch_pilot(
    cache_dir: Path, start: str, symbols: Optional[list[str]] = None, benchmark: str = "SPY"
) -> dict:
    """Fetch adjusted historical bars. Missing symbols are reported, never silently filled."""
    import yfinance as yf

    cache_dir.mkdir(parents=True, exist_ok=True)
    requested = [symbol for symbol in (symbols or PILOT_SYMBOLS) if symbol != benchmark]
    completed, failures = [], {}
    for symbol in requested + [benchmark, "^VIX"]:
        try:
            frame = yf.download(symbol, start=start, auto_adjust=False, progress=False, threads=False)
            if frame.empty:
                raise ValueError("empty response")
            if isinstance(frame.columns, pd.MultiIndex):
                frame.columns = frame.columns.get_level_values(0)
            frame.index = pd.to_datetime(frame.index).tz_localize(None)
            frame.to_parquet(cache_path(cache_dir, symbol))
            completed.append(symbol)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Cache successful symbols even when the remote source fails.
            failures[symbol] = str(exc)
    manifest = {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Yahoo Finance via yfinance",
        "status": "SURVIVORSHIP_BIASED_PILOT",
        "requested_symbols": requested,
        "benchmark": benchmark,
        "completed_symbols": completed,
        "failures": failures,
    }
    (cache_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_pilot(cache_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series]:
    manifest = json.loads((cache_dir / "manifest.json").read_text(encoding="utf-8"))
    symbols = [s for s in manifest["completed_symbols"] if s not in {"^VIX", manifest["benchmark"]}]
    fields: dict[str, dict[str, pd.Series]] = {"Open": {}, "Close": {}, "Volume": {}}
    for symbol in symbols:
        frame = pd.read_parquet(cache_path(cache_dir, symbol))
        for field, field_map in fields.items():
            if field in frame:
                field_map[symbol] = frame[field]
    vix = pd.read_parquet(cache_path(cache_dir, "^VIX"))["Close"].rename("vix")
    return (
        pd.DataFrame(fields["Open"]).sort_index(),
        pd.DataFrame(fields["Close"]).sort_index(),
        pd.DataFrame(fields["Volume"]).sort_index(),
        vix.sort_index(),
    )


def load_benchmark(cache_dir: Path, benchmark: str = "SPY") -> pd.Series:
    """Return adjusted-close benchmark separately from the eligible stock universe."""
    frame = pd.read_parquet(cache_path(cache_dir, benchmark))
    column = "Adj Close" if "Adj Close" in frame else "Close"
    return frame[column].rename(benchmark).sort_index()


def audit_cache(cache_dir: Path) -> dict:
    manifest_path = cache_dir / "manifest.json"
    if not manifest_path.exists():
        return {"status": "NO_CACHE", "message": "Run fetch first."}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bars = {}
    for symbol in manifest["completed_symbols"]:
        frame = pd.read_parquet(cache_path(cache_dir, symbol))
        bars[symbol] = {"start": str(frame.index.min().date()), "end": str(frame.index.max().date()), "bars": len(frame)}
    snapshot = cache_dir / "universe_snapshot.json"
    return {
        "status": manifest["status"],
        "source": manifest["source"],
        "universe_snapshot": json.loads(snapshot.read_text(encoding="utf-8")) if snapshot.exists() else None,
        "failures": manifest["failures"],
        "coverage": bars,
    }
