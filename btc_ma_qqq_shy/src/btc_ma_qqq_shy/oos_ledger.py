"""Append-only frozen OOS weekly ledger. Never rewrite historical rows."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from .config import ProjectConfig
from .data import load_adj_close
from .execution_costs import monday_8am_et_as_utc
from .reconciliation import (
    fetch_bitfinex_btc,
    lean_roc,
    lean_sma,
    load_ohlc_symbol,
    week_start_equity_dates,
)

LEDGER_COLUMNS = [
    "week_id",
    "decision_timestamp",
    "btc_asof_timestamp",
    "btc_close",
    "sma50",
    "mom20",
    "signal",
    "target",
    "execution_timestamp",
    "execution_price",
    "qqq_total_return",
    "shy_total_return",
    "strategy_return",
    "cost",
    "rule_id",
    "row_hash",
    "prev_row_hash",
    "recorded_utc",
]


def ledger_path(config: ProjectConfig) -> Path:
    rel = config.raw.get("oos", {}).get("ledger_path", "reports/frozen_oos_ledger.csv")
    return config.project_root / rel


def oos_cutoff(config: ProjectConfig) -> pd.Timestamp:
    return pd.Timestamp(config.raw["oos"]["cutoff_date"]).normalize()


def _row_hash(row: dict, prev: str) -> str:
    payload = {k: row.get(k) for k in LEDGER_COLUMNS if k not in ("row_hash", "prev_row_hash", "recorded_utc")}
    payload["prev_row_hash"] = prev
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def _read_ledger(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    df = pd.read_csv(path)
    for c in LEDGER_COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA
    return df[LEDGER_COLUMNS]


def _assert_immutable(existing: pd.DataFrame, incoming: pd.DataFrame) -> None:
    if existing.empty:
        return
    overlap = set(existing["week_id"].astype(str)) & set(incoming["week_id"].astype(str))
    for wid in sorted(overlap):
        old = existing.loc[existing["week_id"].astype(str) == wid].iloc[0]
        new = incoming.loc[incoming["week_id"].astype(str) == wid].iloc[0]
        keys = [
            "decision_timestamp",
            "btc_asof_timestamp",
            "btc_close",
            "sma50",
            "mom20",
            "signal",
            "target",
            "execution_timestamp",
            "rule_id",
        ]
        for k in keys:
            ov, nv = old[k], new[k]
            if pd.isna(ov) and pd.isna(nv):
                continue
            if str(ov) != str(nv):
                raise RuntimeError(
                    f"OOS ledger immutable violation on week_id={wid} field={k}: "
                    f"existing={ov!r} incoming={nv!r}. Retuning resets the OOS clock."
                )


def generate_oos_candidates(config: ProjectConfig) -> pd.DataFrame:
    """Week-starts on/after OOS cutoff with QC-proxy Mon 08:00 ET decision."""
    cutoff = oos_cutoff(config)
    bf = fetch_bitfinex_btc(config)
    prices = load_adj_close(config)
    qqq_ohlc = load_ohlc_symbol(config, "QQQ")
    shy_ohlc = load_ohlc_symbol(config, "SHY")
    qqq_adj = prices["QQQ"]
    shy_adj = prices["SHY"]
    qqq_open = qqq_ohlc["Open"].astype(float)
    shy_open = shy_ohlc["Open"].astype(float)
    etf_cal = prices[["QQQ", "SHY"]].dropna().index
    week_starts = list(week_start_equity_dates(etf_cal))

    sma_n = int(config.raw["rules"]["sma_window"])
    mom_n = int(config.raw["rules"]["momentum_window"])
    rule_id = config.raw["oos"]["frozen_rule_id"]
    one_way = float(config.raw["rules"].get("costs_bps_one_way", 5))
    hs = config.raw["rules"].get("half_spread_bps", {})
    cost_rt_bps = 2.0 * one_way + float(hs.get("QQQ", 0)) + float(hs.get("SHY", 0))

    btc_close = bf["Close"].astype(float)
    sma = lean_sma(btc_close, sma_n)
    roc = lean_roc(btc_close, mom_n)

    # Prior target from last pre-cutoff week
    prev_target = None
    for ws in week_starts:
        if pd.Timestamp(ws) >= cutoff:
            break
        prior = btc_close.loc[btc_close.index < ws].dropna()
        if prior.empty:
            continue
        asof = prior.index[-1]
        if asof not in sma.index or pd.isna(sma.loc[asof]) or pd.isna(roc.loc[asof]):
            continue
        prev_target = "QQQ" if float(btc_close.loc[asof]) > float(sma.loc[asof]) and float(roc.loc[asof]) > 0 else "SHY"

    rows = []
    for i, ws in enumerate(week_starts):
        ws = pd.Timestamp(ws).normalize()
        if ws < cutoff:
            continue
        prior = btc_close.loc[btc_close.index < ws].dropna()
        if prior.empty:
            continue
        asof = pd.Timestamp(prior.index[-1])
        if asof not in sma.index or pd.isna(sma.loc[asof]) or pd.isna(roc.loc[asof]):
            continue
        px = float(btc_close.loc[asof])
        s50 = float(sma.loc[asof])
        roc_v = float(roc.loc[asof])
        signal = bool(px > s50 and roc_v > 0.0)
        target = "QQQ" if signal else "SHY"
        if ws not in qqq_open.index or ws not in shy_open.index:
            continue
        exec_px = float(qqq_open.loc[ws] if target == "QQQ" else shy_open.loc[ws])

        # Holding week complete?
        if i + 1 >= len(week_starts):
            qqq_r = shy_r = strat_r = np.nan
            cost = 0.0
        else:
            end = week_starts[i + 1]
            days = etf_cal[(etf_cal >= ws) & (etf_cal < end)]
            qqq_r = float((1 + qqq_adj.pct_change().reindex(days).fillna(0.0)).prod() - 1.0)
            shy_r = float((1 + shy_adj.pct_change().reindex(days).fillna(0.0)).prod() - 1.0)
            gross = qqq_r if target == "QQQ" else shy_r
            cost = (cost_rt_bps / 10000.0) if (prev_target is not None and prev_target != target) else 0.0
            strat_r = gross - cost

        rows.append(
            {
                "week_id": str(ws.date()),
                "decision_timestamp": monday_8am_et_as_utc(ws).isoformat(sep=" "),
                "btc_asof_timestamp": asof.isoformat(sep=" "),
                "btc_close": px,
                "sma50": s50,
                "mom20": roc_v / 100.0,
                "signal": int(signal),
                "target": target,
                "execution_timestamp": f"{ws.date().isoformat()} 09:30:00 ET",
                "execution_price": exec_px,
                "qqq_total_return": qqq_r,
                "shy_total_return": shy_r,
                "strategy_return": strat_r,
                "cost": cost,
                "rule_id": rule_id,
            }
        )
        prev_target = target
    return pd.DataFrame(rows)


def append_oos_ledger(config: ProjectConfig, *, dry_run: bool = False) -> dict[str, Any]:
    path = ledger_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_ledger(path)
    candidates = generate_oos_candidates(config)
    if candidates.empty:
        return {
            "appended": 0,
            "ledger": str(path),
            "n_existing": int(len(existing)),
            "cutoff": str(oos_cutoff(config).date()),
            "message": "no candidates",
        }

    finished = candidates.dropna(subset=["strategy_return"])
    existing_ids = set(existing["week_id"].astype(str)) if len(existing) else set()
    new = finished.loc[~finished["week_id"].astype(str).isin(existing_ids)].copy()
    if len(new) == 0:
        return {
            "appended": 0,
            "ledger": str(path),
            "n_existing": int(len(existing)),
            "cutoff": str(oos_cutoff(config).date()),
            "message": "ledger up to date",
            "pending_incomplete_weeks": list(
                candidates.loc[candidates["strategy_return"].isna(), "week_id"].astype(str)
            ),
        }

    _assert_immutable(existing, new)

    prev_hash = ""
    if len(existing) and pd.notna(existing.iloc[-1]["row_hash"]):
        prev_hash = str(existing.iloc[-1]["row_hash"])

    out_rows = []
    for _, r in new.iterrows():
        d = {c: r.get(c) for c in LEDGER_COLUMNS if c not in ("row_hash", "prev_row_hash", "recorded_utc")}
        d["prev_row_hash"] = prev_hash
        d["recorded_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        h = _row_hash(d, prev_hash)
        d["row_hash"] = h
        out_rows.append(d)
        prev_hash = h

    add = pd.DataFrame(out_rows)[LEDGER_COLUMNS]
    if dry_run:
        return {"appended": int(len(add)), "dry_run": True, "weeks": list(add["week_id"])}

    combined = pd.concat([existing, add], ignore_index=True) if len(existing) else add
    tmp = path.with_suffix(".csv.tmp")
    combined.to_csv(tmp, index=False)
    tmp.replace(path)

    snap = (
        path.parent
        / "oos_snapshots"
        / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_ledger.csv"
    )
    snap.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(snap, index=False)

    return {
        "appended": int(len(add)),
        "ledger": str(path),
        "n_total": int(len(combined)),
        "weeks": list(add["week_id"]),
        "cutoff": str(oos_cutoff(config).date()),
        "rule_id": config.raw["oos"]["frozen_rule_id"],
        "policy": "append_only_never_rewrite_history",
    }


def ledger_status(config: ProjectConfig) -> dict:
    path = ledger_path(config)
    df = _read_ledger(path)
    return {
        "path": str(path),
        "cutoff": str(oos_cutoff(config).date()),
        "n_rows": int(len(df)),
        "week_ids": list(df["week_id"].astype(str)) if len(df) else [],
        "rule_id": config.raw["oos"]["frozen_rule_id"],
        "retune_resets_oos_clock": True,
    }
