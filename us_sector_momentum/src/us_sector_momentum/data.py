"""Yahoo Finance price cache with sibling reuse, snapshots, and file hashes."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .config import SectorConfig


def cache_path(prices_dir: Path, symbol: str) -> Path:
    return prices_dir / f"{symbol.replace('^', '').replace('-', '_')}.parquet"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sibling_roots(config: SectorConfig) -> list[Path]:
    return [(config.project_root / rel).resolve() for rel in config.universe.get("sibling_cache_roots", [])]


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


def _cache_start(path: Path) -> Optional[pd.Timestamp]:
    try:
        idx = read_parquet_safe(path).index
        return pd.Timestamp(idx.min()) if len(idx) else None
    except (OSError, ValueError, KeyError):
        return None


def _is_adequately_long(config: SectorConfig, symbol: str, path: Path) -> bool:
    """
    Reject sibling/local caches that start far after ETF inception / research start.

    Sibling tracks often store SPY/sector panels from 2005+; this track needs ~1998/1999.
    """
    start = _cache_start(path)
    if start is None:
        return False
    inception = config.universe.get("inception_approx", {}).get(symbol)
    if inception:
        target = pd.Timestamp(inception) + pd.Timedelta(days=60)
    else:
        target = pd.Timestamp(config.raw["data"]["start"]) + pd.Timedelta(days=60)
    # Allow RF series (BIL) to start at true inception even if later than 1998.
    if symbol in {config.rf_primary, config.rf_proxy}:
        return True
    return start <= target


def reuse_sibling_caches(config: SectorConfig) -> dict[str, str]:
    actions: dict[str, str] = {}
    for symbol in config.price_symbols:
        dst = cache_path(config.prices_dir, symbol)
        if dst.exists():
            if _is_adequately_long(config, symbol, dst):
                actions[symbol] = "local"
                continue
            # Truncated local/symlink — remove so fetch downloads a full history file.
            dst.unlink()
            actions[symbol] = "removed_truncated"
        found = None
        for root in _sibling_roots(config):
            cand = cache_path(root, symbol)
            if cand.exists() and _is_adequately_long(config, symbol, cand):
                found = cand
                break
        if found is None:
            actions[symbol] = actions.get(symbol, "missing")
            if actions[symbol] != "removed_truncated":
                actions[symbol] = "missing"
            else:
                actions[symbol] = "truncated_sibling_skipped"
            continue
        actions[symbol] = _link_or_copy(found, dst)
    return actions


def fetch_prices(
    config: SectorConfig,
    *,
    refresh: bool = False,
    symbols: Optional[list[str]] = None,
) -> dict:
    import yfinance as yf

    reuse_sibling_caches(config)
    prices_dir = config.prices_dir
    prices_dir.mkdir(parents=True, exist_ok=True)
    requested = list(symbols or config.price_symbols)
    start = config.raw["data"]["start"]
    completed: list[str] = []
    failures: dict[str, str] = {}
    actions: dict[str, str] = {}
    hashes: dict[str, str] = {}

    for symbol in requested:
        path = cache_path(prices_dir, symbol)
        if path.exists() and not refresh:
            completed.append(symbol)
            actions[symbol] = "cache_hit"
            hashes[symbol] = file_sha256(path)
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
            if path.exists() or path.is_symlink():
                snap = config.snapshots_dir / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                snap.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(path, snap / path.name)
                except OSError:
                    pass
                # Never overwrite sibling caches through a symlink.
                path.unlink()
            snap_new = config.snapshots_dir / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            snap_new.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(snap_new / path.name)
            frame.to_parquet(path)
            completed.append(symbol)
            actions[symbol] = "downloaded"
            hashes[symbol] = file_sha256(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failures[symbol] = str(exc)
            actions[symbol] = "failed"

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
        "file_sha256": hashes,
        "refuse_silent_stale_on_failed_refresh": True,
    }
    config.cache_dir.mkdir(parents=True, exist_ok=True)
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


def load_ohlc(
    config: SectorConfig, symbols: Optional[list[str]] = None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (adj_open, adj_close, raw_close). Adj Open = Open * (Adj Close / Close)."""
    requested = list(symbols or config.panel_symbols)
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
    return (
        pd.DataFrame(opens).sort_index(),
        pd.DataFrame(adj_closes).sort_index(),
        pd.DataFrame(raw_closes).sort_index(),
    )


def strict_common_index(closes: pd.DataFrame) -> pd.DatetimeIndex:
    mask = closes.notna().all(axis=1)
    return pd.DatetimeIndex(closes.index[mask]).sort_values()


def load_rf_daily(config: SectorConfig, calendar: pd.DatetimeIndex) -> tuple[pd.Series, dict]:
    """
    Daily risk-free total-return proxy for Sharpe.

    - Prefer BIL Adj Close daily returns where available.
    - Before BIL (or gaps): use ^IRX (13-week T-bill yield %) → daily ≈ (yield/100)/252.
    - Disclosure metadata returned alongside the series.
    """
    meta: dict = {
        "rf_primary": config.rf_primary,
        "rf_proxy_pre_bil": config.rf_proxy,
        "method": "BIL_adj_close_returns_with_IRX_daily_yield_proxy_pre_bil",
    }
    bil_path = cache_path(config.prices_dir, config.rf_primary)
    irx_path = cache_path(config.prices_dir, config.rf_proxy)
    bil_ret = None
    if bil_path.exists():
        bil = read_parquet_safe(bil_path)["Adj Close"].reindex(calendar)
        bil_ret = bil.pct_change(fill_method=None)
        meta["bil_start"] = str(bil.dropna().index.min().date()) if bil.notna().any() else None
        meta["bil_end"] = str(bil.dropna().index.max().date()) if bil.notna().any() else None
    else:
        meta["bil_start"] = None
        meta["bil_end"] = None

    irx_daily = None
    if irx_path.exists():
        irx = read_parquet_safe(irx_path)
        # Yahoo ^IRX Close is annualized discount yield in percent.
        yld = irx["Close"].reindex(calendar)
        irx_daily = (yld / 100.0) / 252.0
        meta["irx_start"] = str(yld.dropna().index.min().date()) if yld.notna().any() else None
        meta["irx_end"] = str(yld.dropna().index.max().date()) if yld.notna().any() else None
        meta["irx_note"] = "Close yield percent / 100 / 252 as daily rf proxy"
    else:
        meta["irx_start"] = None
        meta["irx_end"] = None

    if bil_ret is None and irx_daily is None:
        raise FileNotFoundError("need BIL and/or ^IRX for risk-free series")

    out = pd.Series(index=calendar, dtype=float)
    source = pd.Series(index=calendar, dtype=object)
    for date in calendar:
        b = bil_ret.at[date] if bil_ret is not None else np.nan
        i = irx_daily.at[date] if irx_daily is not None else np.nan
        if pd.notna(b):
            out.at[date] = float(b)
            source.at[date] = "BIL"
        elif pd.notna(i):
            out.at[date] = float(i)
            source.at[date] = "IRX_proxy"
        else:
            out.at[date] = np.nan
            source.at[date] = "missing"
    meta["n_bil_days"] = int((source == "BIL").sum())
    meta["n_irx_proxy_days"] = int((source == "IRX_proxy").sum())
    meta["n_missing_rf"] = int((source == "missing").sum())
    meta["source_by_day_sample"] = {
        "first": str(source.dropna().iloc[0]) if source.notna().any() else None,
        "last": str(source.dropna().iloc[-1]) if source.notna().any() else None,
    }
    return out.rename("rf"), meta


def audit_prices(
    config: SectorConfig,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    raw_closes: pd.DataFrame,
) -> dict:
    common = strict_common_index(closes[config.panel_symbols])
    per_symbol = {}
    extreme_flags = []
    split_like = []
    for symbol in config.panel_symbols:
        series = closes[symbol].dropna()
        raw = raw_closes[symbol].dropna()
        dups = int(series.index.duplicated().sum())
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
        raw_rets = raw.pct_change(fill_method=None).dropna()
        # Split-like: large raw move with small adj move
        aligned = pd.concat([raw_rets.rename("raw"), rets.rename("adj")], axis=1).dropna()
        suspects = aligned[(aligned["raw"].abs() > 0.20) & (aligned["adj"].abs() < 0.05)]
        for date, row in suspects.iterrows():
            split_like.append(
                {
                    "symbol": symbol,
                    "date": str(pd.Timestamp(date).date()),
                    "raw_ret": float(row["raw"]),
                    "adj_ret": float(row["adj"]),
                }
            )
        factor = (series.reindex(raw.index) / raw).dropna()
        # Dividend-like: adj factor drifts vs raw without huge raw gap
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
            "n_split_like_flags": int(len(suspects)),
        }

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
        "extreme_flags_sample": extreme_flags[:40],
        "n_extreme_flags": len(extreme_flags),
        "split_like_sample": split_like[:40],
        "n_split_like_flags": len(split_like),
        "manifest": manifest,
        "notes": [
            "Signals and NAV use dividend-adjusted total return (Adj Close).",
            "Open scaled by AdjClose/Close for overnight coherence.",
            "Missing returns are never fillna(0); panels trimmed to strict common dates.",
            "QQQ inception ~1999-03; common panel starts at intersection of nine sectors + SPY + QQQ.",
        ],
    }
