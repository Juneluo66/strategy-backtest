"""Serial ETF data cache, point-in-time eligibility, and coverage audit."""
from __future__ import annotations

import time
from multiprocessing import Process, Queue
from pathlib import Path

import akshare as ak
import pandas as pd
import yaml

from etf_rotation.config import RotationConfig


def _fetch_worker(code: str, target: str, result: Queue) -> None:
    """Isolated process: a stalled vendor call can be terminated by its parent."""
    try:
        try:
            raw = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
            source = "eastmoney_qfq"
        except Exception as eastmoney_error:  # noqa: BLE001 - documented fallback
            market_prefix = "sh" if code.startswith(("5", "51", "52", "58")) else "sz"
            try:
                raw = ak.fund_etf_hist_sina(symbol=f"{market_prefix}{code}")
                source = "sina_unadjusted"
            except Exception as sina_error:
                raise RuntimeError(
                    f"Eastmoney failed: {eastmoney_error}; Sina fallback failed: {sina_error}"
                ) from sina_error
        normalized = normalize_prices(raw, code)
        normalized["source"] = source
        normalized.to_parquet(target, index=False)
        result.put(None)
    except Exception as error:  # noqa: BLE001 - report worker failure to retry loop
        result.put(str(error))


def universe_definition(config: RotationConfig) -> pd.DataFrame:
    path = config.project_root / "configs" / "etf_universe.yaml"
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)["universe"]
    qdii = set(data["qdii"])
    return pd.DataFrame(
        {"code": data["symbols"], "is_qdii": [code in qdii for code in data["symbols"]]}
    )


def price_path(config: RotationConfig, code: str) -> Path:
    return config.cache_dir / "prices" / f"{code}.parquet"


def normalize_prices(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    """Normalize Eastmoney ETF history to a minimal, explicit schema."""
    names = {
        "日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
        "成交量": "volume", "成交额": "amount", "涨跌幅": "pct_change",
    }
    out = frame.rename(columns=names).copy()
    required = ["date", "open", "close", "high", "low", "volume", "amount"]
    missing = set(required).difference(out.columns)
    if missing:
        raise ValueError(f"{code}: missing expected data columns {sorted(missing)}")
    out = out[required + (["pct_change"] if "pct_change" in out else [])]
    out["date"] = pd.to_datetime(out["date"])
    for column in required[1:]:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out["code"] = code
    return out.dropna(subset=["date", "open", "close"]).sort_values("date").drop_duplicates("date")


def fetch_one(config: RotationConfig, code: str, refresh: bool = False, request_timeout: int = 60) -> Path:
    path = price_path(config, code)
    if path.exists() and not refresh:
        try:
            existing = pd.read_parquet(path, columns=["date", "open", "close"])
            if not existing.empty and not existing["date"].duplicated().any():
                return path
        except Exception as error:  # noqa: BLE001 - corrupt cache must be redownloaded
            (config.cache_dir / "cache_read_failures.log").parent.mkdir(parents=True, exist_ok=True)
            with (config.cache_dir / "cache_read_failures.log").open("a", encoding="utf-8") as handle:
                handle.write(f"{code}: {error}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    queue: Queue = Queue(maxsize=1)
    worker = Process(target=_fetch_worker, args=(code, str(path), queue))
    worker.start()
    worker.join(request_timeout)
    if worker.is_alive():
        worker.terminate()
        worker.join()
        raise TimeoutError(f"{code}: AkShare request exceeded {request_timeout}s")
    if worker.exitcode != 0:
        raise RuntimeError(f"{code}: AkShare worker exited with {worker.exitcode}")
    error = queue.get_nowait() if not queue.empty() else None
    if error:
        raise RuntimeError(f"{code}: {error}")
    if not path.exists():
        raise RuntimeError(f"{code}: AkShare worker completed without cache output")
    return path


def cached_prices(config: RotationConfig, codes: list[str] | None = None) -> dict[str, pd.DataFrame]:
    selected = set(codes or [])
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted((config.cache_dir / "prices").glob("*.parquet")):
        code = path.stem
        if selected and code not in selected:
            continue
        frame = pd.read_parquet(path)
        frame["date"] = pd.to_datetime(frame["date"])
        frames[code] = frame.sort_values("date")
    return frames


def build_pit_universe(prices: dict[str, pd.DataFrame], definition: pd.DataFrame,
                       min_history: int) -> pd.DataFrame:
    """Per-date candidate set; first observed bar is the conservative listing proxy."""
    records = []
    meta = definition.set_index("code")
    for code, frame in prices.items():
        if code not in meta.index or frame.empty:
            continue
        frame = frame.sort_values("date").reset_index(drop=True)
        eligible = frame.index >= min_history
        if meta.loc[code, "is_qdii"]:
            eligible &= False
        records.extend(
            {"date": date, "code": code, "is_qdii": bool(meta.loc[code, "is_qdii"]),
             "eligible": bool(ok), "listing_proxy_date": frame["date"].iloc[0]}
            for date, ok in zip(frame["date"], eligible)
        )
    return pd.DataFrame(records)


def fetch_many(config: RotationConfig, limit: int, full: bool, refresh: bool,
               sleep_seconds: float, rss_check, retries: int = 4, request_timeout: int = 60) -> pd.DataFrame:
    definition = universe_definition(config)
    if not full:
        # The regime proxy is mandatory for every smoke backtest, even when
        # the deterministic smoke subset does not otherwise contain it.
        proxy = definition.loc[definition["code"].eq(config.regime_proxy)]
        remainder = definition.loc[~definition["code"].eq(config.regime_proxy)].head(max(limit - len(proxy), 0))
        definition = pd.concat([proxy, remainder], ignore_index=True)
    failures = []
    for index, code in enumerate(definition["code"], start=1):
        error = None
        for attempt in range(retries + 1):
            try:
                fetch_one(config, code, refresh, request_timeout)
                error = None
                break
            except Exception as caught:  # noqa: BLE001 - persist the remote failure
                error = caught
                if attempt < retries:
                    time.sleep(sleep_seconds * (2 ** attempt))
        if error is not None:
            failures.append({"code": code, "error": str(error), "attempts": retries + 1})
        rss_check(completed=index, requested=len(definition), failed=len(failures))
        time.sleep(sleep_seconds)
    report = pd.DataFrame(failures)
    if not report.empty:
        report.to_csv(config.cache_dir / "fetch_failures.csv", index=False)
    return report


def coverage_audit(config: RotationConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    definition = universe_definition(config)
    rows = []
    for record in definition.itertuples(index=False):
        path = price_path(config, record.code)
        if path.exists():
            frame = pd.read_parquet(path, columns=["date"])
            dates = pd.to_datetime(frame["date"])
            rows.append({"code": record.code, "is_qdii": record.is_qdii, "cached": True,
                         "bars": len(dates), "first_date": dates.min(), "last_date": dates.max()})
        else:
            rows.append({"code": record.code, "is_qdii": record.is_qdii, "cached": False,
                         "bars": 0, "first_date": pd.NaT, "last_date": pd.NaT})
    detail = pd.DataFrame(rows)
    summary = pd.DataFrame([{
        "universe_size": len(detail), "cached_symbols": int(detail["cached"].sum()),
        "missing_symbols": int((~detail["cached"]).sum()), "qdii_symbols": int(detail["is_qdii"].sum()),
        "earliest_cached_date": detail["first_date"].min(), "latest_cached_date": detail["last_date"].max(),
    }])
    return summary, detail
