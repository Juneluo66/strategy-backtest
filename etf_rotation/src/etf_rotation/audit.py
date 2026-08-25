"""Data-quality and factor-completeness audits; never silently repair inputs."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from etf_rotation.config import RotationConfig
from etf_rotation.data import cached_prices, universe_definition
from etf_rotation.non_ohlcv.shares import share_source_status

# Per-factor block reasons from reports/non_ohlcv_source_research.md. Do not
# promote status to available until a versioned PIT parquet exists and passes
# missing_ratio < 0.05 plus no-lookahead tests.
_FACTOR_BLOCK_NOTES = {
    "MARGIN_BUY_RATIO": (
        "Exchange margin detail (SSE/SZSE via AkShare) is a candidate raw source, "
        "but no versioned PIT parquet is wired; absent codes stay missing (not zero). "
        "See reports/non_ohlcv_source_research.md."
    ),
    "MARGIN_CHG_10D": (
        "Same as MARGIN_BUY_RATIO: rzye day-detail candidate exists, production "
        "cache not enabled without calendar available_at + coverage audit. "
        "See reports/non_ohlcv_source_research.md."
    ),
    "SHARE_CHG_5D": (
        "Daily ETF share history requires TuShare etf_share_size/QMT; no audited "
        "tokenized dump. Quarterly scale pages cannot build 5D changes. "
        "See reports/non_ohlcv_source_research.md."
    ),
    "SHARE_CHG_20D": (
        "Daily ETF share history requires TuShare etf_share_size/QMT; no audited "
        "tokenized dump. Quarterly scale pages cannot build 20D changes. "
        "See reports/non_ohlcv_source_research.md."
    ),
}


def _names() -> dict[str, str]:
    """Best-effort current name mapping; failure remains explicit in the audit."""
    try:
        import akshare as ak

        spot = ak.fund_etf_spot_em()
        return dict(zip(spot["代码"].astype(str), spot["名称"].astype(str)))
    except Exception:  # noqa: BLE001 - data source availability is an audit finding
        return {}


def data_audit(config: RotationConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    prices = cached_prices(config)
    universe = universe_definition(config).set_index("code")
    names = _names()
    expected = set().union(*(set(frame["date"]) for frame in prices.values())) if prices else set()
    rows = []
    for code, meta in universe.iterrows():
        frame = prices.get(code)
        if frame is None or frame.empty:
            rows.append({
                "code": code, "name": names.get(code, "unavailable"), "listing_date": pd.NaT,
                "first_available_date": pd.NaT, "last_available_date": pd.NaT,
                "coverage_ratio": 0.0, "missing_trading_days": len(expected), "duplicate_records": 0,
                "pre_listing_rows": 0, "ohlc_anomalies": 0, "volume_amount_anomalies": 0,
                "max_consecutive_missing_days": pd.NA, "suspension_like_rows": 0,
                "adjustment_basis": "qfq", "name_lookup_available": bool(names),
                "is_qdii": bool(meta.is_qdii), "audit_pass": False, "audit_failure_reason": "missing_cache",
            })
            continue
        dates = pd.to_datetime(frame["date"])
        first, last = dates.min(), dates.max()
        duplicate = int(dates.duplicated().sum())
        missing = len(expected.difference(set(dates)))
        ohlc = ((frame["low"] > frame[["open", "close", "high"]].min(axis=1)) |
                (frame["high"] < frame[["open", "close", "low"]].max(axis=1))).sum()
        bad_liquidity = ((frame["volume"] < 0) | (frame["amount"] < 0)).sum()
        suspension = ((frame["volume"].fillna(0) == 0) | (frame["amount"].fillna(0) == 0)).sum()
        sources = "|".join(sorted(frame.get("source", pd.Series(["unknown"])).dropna().astype(str).unique()))
        sorted_dates = dates.sort_values().drop_duplicates()
        gaps = sorted_dates.diff().dt.days.sub(1).clip(lower=0)
        max_gap = int(gaps.max()) if gaps.notna().any() else 0
        failures = []
        if duplicate:
            failures.append("duplicate_dates")
        if ohlc:
            failures.append("ohlc_relation")
        if bad_liquidity:
            failures.append("negative_volume_or_amount")
        if len(frame) < config.lookback + 1:
            failures.append("insufficient_lookback")
        rows.append({
            "code": code, "name": names.get(code, "unavailable"), "listing_date": first,
            "first_available_date": first, "last_available_date": last,
            "coverage_ratio": len(dates) / len(expected) if expected else pd.NA,
            "missing_trading_days": missing, "duplicate_records": duplicate,
            "pre_listing_rows": 0, "ohlc_anomalies": int(ohlc),
            "volume_amount_anomalies": int(bad_liquidity),
            "max_consecutive_missing_days": max_gap, "suspension_like_rows": int(suspension),
            "adjustment_basis": sources, "name_lookup_available": bool(names),
            "is_qdii": bool(meta.is_qdii), "audit_pass": not failures,
            "audit_failure_reason": "|".join(failures) if failures else "",
        })
    detail = pd.DataFrame(rows)
    coverage = detail[[
        "code", "name", "listing_date", "first_available_date", "last_available_date",
        "coverage_ratio", "missing_trading_days", "duplicate_records", "is_qdii", "audit_pass",
    ]].copy()
    factors = ["MARGIN_BUY_RATIO", "MARGIN_CHG_10D", "SHARE_CHG_5D", "SHARE_CHG_20D"]
    share_status = share_source_status()
    manifest_path = config.cache_dir / "non_ohlcv" / "production_manifest.json"
    manifest_status = None
    if manifest_path.exists():
        import json

        manifest_status = json.loads(manifest_path.read_text(encoding="utf-8")).get("status")
    factor_rows = []
    for factor in factors:
        path = config.cache_dir / "non_ohlcv" / f"{factor}.parquet"
        if path.exists():
            supplied = pd.read_parquet(path)
            missing_ratio = (
                float(supplied["value"].isna().mean()) if "value" in supplied else 1.0
            )
            pit_ok = True
            if {"available_at", "date"}.issubset(supplied.columns):
                pit_ok = bool(
                    (pd.to_datetime(supplied["available_at"]) <= pd.to_datetime(supplied["date"])).all()
                )
            production_ok = (
                manifest_status == "production"
                and missing_ratio < 0.05
                and pit_ok
            )
            if production_ok:
                status = "production"
                note = "Production TuShare PIT cache; missing inputs remain NaN (no zero fill)."
            elif missing_ratio < 0.05 and pit_ok:
                status = "partial_unavailable"
                note = (
                    "Parquet present with low missing_ratio but production_manifest "
                    "not approved; keep partial until fetch-non-ohlcv validation promotes."
                )
            else:
                status = "partial_unavailable"
                note = (
                    f"Cached but missing_ratio={missing_ratio:.3f} or PIT fail; keep partial."
                )
            factor_rows.append({
                "factor": factor, "source_path": str(path), "status": status,
                "missing_ratio": missing_ratio,
                "affected_dates": int(supplied["value"].isna().sum()) if "value" in supplied else pd.NA,
                "note": note,
            })
        else:
            note = _FACTOR_BLOCK_NOTES[factor]
            if factor.startswith("SHARE_"):
                note = f"{note} | {share_status.reason}"
            factor_rows.append({
                "factor": factor, "source_path": str(path), "status": "partial_unavailable",
                "missing_ratio": 1.0, "affected_dates": len(expected),
                "note": note,
            })
    return detail, coverage, pd.DataFrame(factor_rows)


def render_data_audit(detail: pd.DataFrame, factors: pd.DataFrame, path: Path) -> None:
    summary = pd.DataFrame([{
        "symbols": len(detail), "passed": int(detail["audit_pass"].sum()),
        "failed": int((~detail["audit_pass"]).sum()),
        "partial_factors": int((~factors.status.isin(["production", "available"])).sum()),
    }])
    text = [
        "# Data audit",
        "",
        summary.to_markdown(index=False),
        "",
        "## Required controls",
        "",
        "- Signal factors use T-close data; execution is scheduled for the next available session open.",
        "- Adjustment/source basis is shown per symbol. Sina fallback is unadjusted and blocks a clean qfq-equivalent comparison.",
        "- QDII is excluded from trading in `A_SHARE_ONLY`; its overseas close timing is therefore never used for a trade signal.",
        "- Zero volume/amount rows are recorded as suspension-like observations and are not silently converted into fills.",
        "- Listing date is the first vendor-available bar proxy, not a fund-contract primary source.",
        "",
        "## Partial non-OHLCV factors",
        "",
        factors.to_markdown(index=False),
        "",
        "A partial factor set is never labelled a complete v8 replication.",
        "",
        "Research notes: `reports/non_ohlcv_source_research.md`. "
        "Status remains `BLOCKED_BY_DATA` until all four factors have "
        "`status=production` (`missing_ratio < 0.05` and PIT) via "
        "`etf-rotation fetch-non-ohlcv --full`. See `reports/non_ohlcv_validation.md`.",
    ]
    path.write_text("\n".join(text) + "\n", encoding="utf-8")
