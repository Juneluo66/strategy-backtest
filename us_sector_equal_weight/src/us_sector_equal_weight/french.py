"""Kenneth French 12-industry external mechanism validation (not tradable ETF)."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Optional
from urllib.request import urlopen

import numpy as np
import pandas as pd

from .config import EWConfig
from .schedules import VERSION_FREQ, equal_weight_series

# French daily 12 industry average value-weighted file
FRENCH_DAILY_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "12_Industry_Portfolios_daily_CSV.zip"
)


def fetch_french_12_daily(config: EWConfig, *, refresh: bool = False) -> Path:
    config.french_dir.mkdir(parents=True, exist_ok=True)
    out = config.french_dir / "12_Industry_Portfolios_daily.csv"
    if out.exists() and not refresh:
        return out
    with urlopen(FRENCH_DAILY_URL, timeout=120) as resp:
        payload = resp.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = zf.namelist()
        # Prefer Average Value Weighted Returns -- Daily
        member = names[0]
        for n in names:
            if "daily" in n.lower() or n.lower().endswith(".csv"):
                member = n
                break
        raw = zf.read(member).decode("latin-1")
    out.write_text(raw, encoding="utf-8")
    (config.french_dir / "download_meta.txt").write_text(
        f"url={FRENCH_DAILY_URL}\nmember={member}\n", encoding="utf-8"
    )
    return out


def _parse_french_daily_vw(path: Path) -> pd.DataFrame:
    """Parse Average Value Weighted Returns -- Daily block (comma-separated)."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = None
    for i, line in enumerate(lines):
        if "Average Value Weighted Returns" in line and "Daily" in line:
            start = i + 1
            break
    if start is None:
        for i, line in enumerate(lines):
            if "NoDur" in line and "Enrgy" in line:
                start = i
                break
    if start is None:
        raise ValueError("could not locate French VW daily header")
    while start < len(lines) and not lines[start].strip():
        start += 1
    header = lines[start].lstrip(",")
    cols = [c.strip() for c in header.split(",") if c.strip()]
    rows = []
    for line in lines[start + 1 :]:
        if not line.strip():
            if rows:
                break
            continue
        if "Average Equal" in line or line.strip().lower().startswith("equal"):
            break
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        date_token = parts[0]
        if not date_token.isdigit():
            continue
        rows.append([date_token] + parts[1 : 1 + len(cols)])
    if not rows:
        raise ValueError("no French daily rows parsed")
    frame = pd.DataFrame(rows, columns=["date"] + cols)
    frame["date"] = pd.to_datetime(frame["date"], format="%Y%m%d", errors="coerce")
    frame = frame.dropna(subset=["date"]).set_index("date").sort_index()
    for c in frame.columns:
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    frame = frame / 100.0
    frame = frame.mask(frame <= -0.99)  # -99.99 / -999 sentinels
    return frame


def map_french_to_ew9_legs(french_rets: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """Build nine synthetic legs from pre-registered mapping (equal-weight components)."""
    spec = mapping["etf_to_french_components"]
    out = {}
    for etf, meta in spec.items():
        comps = meta["components"]
        missing = [c for c in comps if c not in french_rets.columns]
        if missing:
            # try strip spaces / match case-insensitive
            rename = {c: c.strip() for c in french_rets.columns}
            french_rets = french_rets.rename(columns=rename)
            missing = [c for c in comps if c not in french_rets.columns]
        if missing:
            raise KeyError(f"{etf}: missing French columns {missing}; have {list(french_rets.columns)}")
        out[etf] = french_rets[comps].mean(axis=1)
    return pd.DataFrame(out).dropna(how="any")


def _rebalance_on_returns(
    returns: pd.DataFrame,
    *,
    frequency: str,
    one_way_bps: float = 0.0,
) -> pd.DataFrame:
    """
    Simple close-to-close EW rebalance on a return panel (French mechanism path).
    Costs optional; default 0 for non-tradable validation.
    Signal = period end; apply new weights from next day (no look-ahead on same day).
    """
    from .schedules import build_ew_targets

    # Fake open=close path: use returns only with weight drift between signal+1
    symbols = list(returns.columns)
    # Build synthetic price levels for schedule helpers
    px = (1 + returns.fillna(0)).cumprod()
    # Use month_end etc on index
    if frequency == "monthly":
        from .calendar import month_end_index
        signals = month_end_index(px.index)
    elif frequency == "quarterly":
        from .schedules import quarter_end_index
        signals = quarter_end_index(px.index)
    elif frequency == "annual":
        from .schedules import year_end_index
        signals = year_end_index(px.index)
    else:
        raise ValueError(frequency)

    w = equal_weight_series(symbols)
    weights = None
    pending = None
    rows = []
    signal_set = set(pd.Timestamp(d) for d in signals)
    for i, date in enumerate(px.index):
        r = returns.loc[date]
        cost = 0.0
        if pending is not None:
            # execute at this day's open ≈ apply before today's return
            if weights is None:
                turnover = float(pending.abs().sum())  # from 0
            else:
                turnover = float((pending - weights).abs().sum())
            cost = turnover * one_way_bps / 10_000.0
            weights = pending
            pending = None
        if weights is None:
            gross = 0.0
        else:
            if r.isna().any():
                continue
            gross = float((weights * r).sum())
            grown = weights * (1.0 + r)
            weights = grown / grown.sum()
        if date in signal_set:
            pending = w.copy()
        if weights is not None:
            rows.append({"date": date, "gross_return": gross, "cost": cost, "net_return": gross - cost})
    eq = pd.DataFrame(rows).set_index("date")
    if not eq.empty:
        eq["equity_net"] = (1 + eq["net_return"]).cumprod()
        eq["equity_gross"] = (1 + eq["gross_return"]).cumprod()
    return eq


def run_french_validation(config: EWConfig, *, refresh: bool = False) -> dict:
    path = fetch_french_12_daily(config, refresh=refresh)
    french = _parse_french_daily_vw(path)
    legs = map_french_to_ew9_legs(french, config.french_mapping)
    # Split pre/post ETF era (~1998-12-16)
    etf_start = pd.Timestamp("1998-12-16")
    results = {}
    for label, panel in {
        "full": legs,
        "pre_etf": legs.loc[legs.index < etf_start],
        "post_etf": legs.loc[legs.index >= etf_start],
    }.items():
        if len(panel) < 252:
            results[label] = {"status": "INSUFFICIENT"}
            continue
        block = {}
        for version, freq in VERSION_FREQ.items():
            eq = _rebalance_on_returns(panel, frequency=freq, one_way_bps=0.0)
            if eq.empty:
                block[version] = {"status": "EMPTY"}
                continue
            years = max((eq.index.max() - eq.index.min()).days / 365.25, 1 / 12)
            nav = eq["equity_net"]
            cagr = float(nav.iloc[-1] ** (1 / years) - 1)
            block[version] = {
                "status": "OK",
                "cagr": cagr,
                "final_wealth": float(nav.iloc[-1]),
                "start": str(eq.index.min().date()),
                "end": str(eq.index.max().date()),
                "n_days": int(len(eq)),
                "tradable": False,
                "role": "economic_mechanism_validation_not_tradable_etf_backtest",
            }
        # EW no-rebalance on French legs
        first = panel.index.min()
        w = equal_weight_series(list(panel.columns))
        # buy-and-hold drift from first day
        wealth = (1 + panel).cumprod()
        # start equal: contribution = mean of relative wealth paths normalized
        # Approximate: portfolio value = mean of (P_i / P_i0)
        rel = wealth / wealth.iloc[0]
        bh = rel.mean(axis=1)
        years = max((bh.index.max() - bh.index.min()).days / 365.25, 1 / 12)
        block["ew9_no_rebalance"] = {
            "status": "OK",
            "cagr": float(bh.iloc[-1] ** (1 / years) - 1),
            "final_wealth": float(bh.iloc[-1]),
            "start": str(bh.index.min().date()),
            "end": str(bh.index.max().date()),
            "tradable": False,
        }
        results[label] = block
    results["mapping"] = config.french_mapping
    results["columns_used"] = list(legs.columns)
    results["french_columns_available"] = list(french.columns)
    results["disclaimer"] = config.french_mapping.get("disclaimer")
    return results
