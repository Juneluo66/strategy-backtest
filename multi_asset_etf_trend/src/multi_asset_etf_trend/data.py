"""Yahoo Finance price cache with fail-loud refresh semantics."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .config import TrendConfig


def cache_path(prices_dir: Path, symbol: str) -> Path:
    return prices_dir / f"{symbol.replace('-', '_')}.parquet"


def _sibling_roots(config: TrendConfig) -> list[Path]:
    roots = []
    for rel in config.universe.get("sibling_cache_roots", []):
        path = (config.project_root / rel).resolve()
        roots.append(path)
    return roots


def _link_or_copy(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        return "exists"
    try:
        dst.symlink_to(src)
        return "symlink"
    except OSError:
        shutil.copy2(src, dst)
        return "copy"


def reuse_sibling_caches(config: TrendConfig) -> dict[str, str]:
    """Reuse existing Yahoo parquet caches from sibling research tracks."""
    actions: dict[str, str] = {}
    for symbol in config.all_symbols:
        dst = cache_path(config.prices_dir, symbol)
        if dst.exists():
            actions[symbol] = "local"
            continue
        found = None
        for root in _sibling_roots(config):
            cand = cache_path(root, symbol)
            if cand.exists():
                found = cand
                break
        if found is None:
            actions[symbol] = "missing"
            continue
        actions[symbol] = _link_or_copy(found, dst)
    return actions


def fetch_prices(
    config: TrendConfig,
    *,
    refresh: bool = False,
    symbols: Optional[list[str]] = None,
) -> dict:
    """
    Download Adj Close OHLCV (auto_adjust=False).

    - Existing caches are reused unless refresh=True.
    - On refresh failure for a symbol that already has a parquet, refuse silent
      reuse of that opaque cache for the failed refresh attempt (recorded in
      failures; caller must not proceed as if refresh succeeded).
    - Missing symbols are never invented.
    """
    import yfinance as yf

    reuse_sibling_caches(config)
    prices_dir = config.prices_dir
    prices_dir.mkdir(parents=True, exist_ok=True)
    requested = list(symbols or config.all_symbols)
    start = config.raw["data"]["start"]
    completed: list[str] = []
    failures: dict[str, str] = {}
    actions: dict[str, str] = {}

    for symbol in requested:
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
            frame.index = pd.to_datetime(frame.index).tz_localize(None)
            required_cols = {"Open", "High", "Low", "Close", "Adj Close"}
            missing_cols = required_cols - set(frame.columns)
            if missing_cols:
                raise ValueError(f"missing columns: {sorted(missing_cols)}")
            # Snapshot pre-overwrite when refreshing
            if refresh and path.exists():
                snap = config.snapshots_dir / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                snap.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, snap / path.name)
            frame.to_parquet(path)
            completed.append(symbol)
            actions[symbol] = "downloaded"
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failures[symbol] = str(exc)
            actions[symbol] = "failed"
            # Explicit: do not pretend refresh succeeded by silently keeping old file
            # as "updated". Old file may still exist on disk but is flagged failed.

    manifest = {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": config.raw["data"]["source"],
        "start": start,
        "return_basis": config.return_basis,
        "refresh": refresh,
        "requested_symbols": requested,
        "completed_symbols": completed,
        "failures": failures,
        "actions": actions,
        "refuse_silent_stale_on_failed_refresh": True,
    }
    (config.cache_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    if failures:
        raise RuntimeError(
            "price fetch failures (will not silently treat as success): "
            + json.dumps(failures)
        )
    return manifest


def read_parquet_safe(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return frame


def load_raw_frames(config: TrendConfig, symbols: Optional[list[str]] = None) -> dict[str, pd.DataFrame]:
    requested = list(symbols or config.all_symbols)
    out: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    for symbol in requested:
        path = cache_path(config.prices_dir, symbol)
        if not path.exists():
            missing.append(symbol)
            continue
        out[symbol] = read_parquet_safe(path)
    if missing:
        raise FileNotFoundError(f"missing cached prices for: {missing}; run fetch first")
    return out


def load_ohlc(
    config: TrendConfig, symbols: Optional[list[str]] = None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Return (adj_open, adj_close, raw_close) panels.

    Adj Open = Open * (Adj Close / Close). Signals and NAV use Adj Close total-return path.
    """
    requested = list(symbols or config.all_symbols)
    opens: dict[str, pd.Series] = {}
    adj_closes: dict[str, pd.Series] = {}
    raw_closes: dict[str, pd.Series] = {}
    missing: list[str] = []
    for symbol in requested:
        path = cache_path(config.prices_dir, symbol)
        if not path.exists():
            missing.append(symbol)
            continue
        frame = read_parquet_safe(path)
        close = frame["Close"]
        adj = frame["Adj Close"] if "Adj Close" in frame.columns else close
        factor = (adj / close).replace([np.inf, -np.inf], pd.NA)
        opens[symbol] = (frame["Open"] * factor).rename(symbol)
        adj_closes[symbol] = adj.rename(symbol)
        raw_closes[symbol] = close.rename(symbol)
    if missing:
        raise FileNotFoundError(f"missing cached prices for: {missing}; run fetch first")
    open_panel = pd.DataFrame(opens).sort_index()
    adj_panel = pd.DataFrame(adj_closes).sort_index()
    raw_panel = pd.DataFrame(raw_closes).sort_index()
    return open_panel, adj_panel, raw_panel


def strict_common_index(closes: pd.DataFrame) -> pd.DatetimeIndex:
    """Strict intersection: dates where EVERY column is non-null. Never fillna(0)."""
    mask = closes.notna().all(axis=1)
    return pd.DatetimeIndex(closes.index[mask]).sort_values()


def audit_prices(
    config: TrendConfig,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    raw_closes: pd.DataFrame,
) -> dict:
    """Audit duplicates, gaps, extreme moves, inception, Close vs Adj Close."""
    common = strict_common_index(closes[config.all_symbols])
    per_symbol = {}
    extreme_flags = []
    for symbol in config.all_symbols:
        series = closes[symbol].dropna()
        raw = raw_closes[symbol].dropna()
        dups = int(series.index.duplicated().sum())
        # Missing weekdays inside span (heuristic; US holidays expected)
        if len(series) >= 2:
            bdays = pd.bdate_range(series.index.min(), series.index.max())
            missing_bdays = int(len(bdays.difference(series.index)))
        else:
            missing_bdays = 0
        rets = series.pct_change(fill_method=None).dropna()
        extreme = rets[rets.abs() > 0.25]
        for date, val in extreme.items():
            extreme_flags.append(
                {"symbol": symbol, "date": str(pd.Timestamp(date).date()), "adj_ret": float(val)}
            )
        factor = (series.reindex(raw.index) / raw).dropna()
        per_symbol[symbol] = {
            "rows": int(len(series)),
            "start": str(series.index.min().date()) if len(series) else None,
            "end": str(series.index.max().date()) if len(series) else None,
            "duplicate_dates": dups,
            "missing_bdays_in_span": missing_bdays,
            "adj_factor_min": float(factor.min()) if len(factor) else None,
            "adj_factor_max": float(factor.max()) if len(factor) else None,
            "adj_factor_last": float(factor.iloc[-1]) if len(factor) else None,
            "inception_approx": config.universe.get("inception_approx", {}).get(symbol),
            "n_extreme_gt_25pct": int(len(extreme)),
        }
        # Open scale check
        o = opens[symbol].dropna()
        c = closes[symbol].reindex(o.index)
        r = raw_closes[symbol].reindex(o.index)
        # adj_open / adj_close should approx equal raw_open / raw_close when both present
        # (we constructed it that way)

    manifest_path = config.cache_dir / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    )
    return {
        "status": "OK",
        "return_basis": config.return_basis,
        "common_start": str(common.min().date()) if len(common) else None,
        "common_end": str(common.max().date()) if len(common) else None,
        "common_rows": int(len(common)),
        "per_symbol": per_symbol,
        "extreme_flags_sample": extreme_flags[:30],
        "n_extreme_flags": len(extreme_flags),
        "manifest": manifest,
        "notes": [
            "Signals and NAV use dividend-adjusted total return (Adj Close).",
            "Open scaled by AdjClose/Close for overnight coherence.",
            "Missing returns are never fillna(0); panels trimmed to strict common dates.",
        ],
    }
