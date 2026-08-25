from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import V2Config


def cache_path(prices_dir: Path, symbol: str) -> Path:
    return prices_dir / f"{symbol.replace('-', '_').replace('^', '')}.parquet"


def bitfinex_cache_path(config: V2Config) -> Path:
    shared = config.shared_v1_prices_dir
    if shared and (shared / "BITFINEX_BTCUSD.parquet").exists():
        return shared / "BITFINEX_BTCUSD.parquet"
    return cache_path(config.prices_dir, "BITFINEX_BTCUSD")


def fetch_prices(config: V2Config, *, refresh: bool = False) -> dict:
    import yfinance as yf

    prices_dir = config.prices_dir
    prices_dir.mkdir(parents=True, exist_ok=True)
    completed: list[str] = []
    failures: dict[str, str] = {}
    start = config.raw["data"]["start"]

    for symbol in config.all_symbols():
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
            frame = frame.rename_axis("date").reset_index()
            frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
            frame = frame.set_index("date").sort_index()
            keep = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in frame.columns]
            frame[keep].to_parquet(path)
            completed.append(symbol)
        except Exception as exc:  # noqa: BLE001
            failures[symbol] = str(exc)

    # Bitfinex BTC — read-only from v1 cache or fetch to v2 only
    bf_path = bitfinex_cache_path(config)
    if not bf_path.exists() or refresh:
        try:
            fetch_bitfinex_btc(config, refresh=True)
            completed.append("BITFINEX_BTCUSD")
        except Exception as exc:  # noqa: BLE001
            failures["BITFINEX_BTCUSD"] = str(exc)

    return {"completed": completed, "failures": failures}


def fetch_bitfinex_btc(config: V2Config, *, refresh: bool = False) -> pd.DataFrame:
    path = bitfinex_cache_path(config)
    shared = config.shared_v1_prices_dir
    if path.exists() and not refresh and shared and path.parent == shared:
        return pd.read_parquet(path)
    v2_path = cache_path(config.prices_dir, "BITFINEX_BTCUSD")
    if v2_path.exists() and not refresh:
        return pd.read_parquet(v2_path)
    import ccxt

    ex = ccxt.bitfinex({"enableRateLimit": True})
    since = ex.parse8601("2013-01-01T00:00:00Z")
    rows: list = []
    while True:
        batch = ex.fetch_ohlcv("BTC/USD", timeframe="1d", since=since, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        since = batch[-1][0] + 86_400_000
        if len(batch) < 1000:
            break
    df = pd.DataFrame(rows, columns=["ts", "Open", "High", "Low", "Close", "Volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    df = df.drop_duplicates("date").set_index("date").sort_index()
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    v2_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(v2_path)
    return df


def load_adj_close(config: V2Config, symbols: list[str] | None = None) -> pd.DataFrame:
    syms = symbols or config.all_symbols()
    cols = {}
    for symbol in syms:
        path = cache_path(config.prices_dir, symbol)
        if not path.exists():
            raise FileNotFoundError(f"missing {symbol}: run fetch first")
        frame = pd.read_parquet(path)
        if "Adj Close" not in frame.columns:
            raise KeyError(f"{symbol} missing Adj Close")
        s = frame["Adj Close"].astype(float)
        s.index = pd.to_datetime(s.index).tz_localize(None)
        cols[symbol] = s
    return pd.DataFrame(cols).sort_index()


def load_ohlc(config: V2Config, symbol: str) -> pd.DataFrame:
    path = cache_path(config.prices_dir, symbol)
    if not path.exists():
        raise FileNotFoundError(f"missing {symbol}")
    frame = pd.read_parquet(path)
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    return frame


def cost_rt_bps(config: V2Config, on_sym: str, off_sym: str) -> float:
    ex = config.raw.get("execution", {})
    one_way = float(ex.get("costs_bps_one_way", 5))
    hs = ex.get("half_spread_bps", {})
    h_on = float(hs.get(on_sym, 2.0))
    h_off = float(hs.get(off_sym, 2.0))
    return 2.0 * one_way + h_on + h_off
