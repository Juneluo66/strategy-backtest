"""Pluggable universe providers. Historical S&P500 is approximate, not full PIT."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Optional, Protocol

import pandas as pd

from .schemas import validate_membership_events
from .status import research_status


@dataclass(frozen=True)
class ProviderCapabilities:
    membership_history: bool
    market_cap_history: bool
    delisting_returns: bool


class UniverseProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    def status(self) -> dict: ...
    def symbols_on(self, date: pd.Timestamp) -> frozenset[str]: ...
    def all_symbols(self) -> list[str]: ...
    def index_exits(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame: ...


class StaticPilotProvider:
    """Current-constituent backfill; full survivorship bias."""

    name = "static_current_sp500"
    capabilities = ProviderCapabilities(False, False, False)

    def __init__(self, symbols: list[str]):
        self._symbols = frozenset(symbols)

    def status(self) -> dict:
        return research_status(historical_membership=False)

    def symbols_on(self, date: pd.Timestamp) -> frozenset[str]:
        return self._symbols

    def all_symbols(self) -> list[str]:
        return sorted(self._symbols)

    def index_exits(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        return pd.DataFrame(columns=["date", "symbol", "event", "reason", "delisting_return_status"])


class HistoricalSP500Provider:
    """Rebuild membership by reversing Wikipedia changes from the current list.

    Wikipedia publishes only selected changes, so this reduces — but does not
    eliminate — survivorship bias. PIT_VALIDATED remains false.
    """

    name = "historical_sp500_wikipedia"
    capabilities = ProviderCapabilities(True, False, False)

    def __init__(self, events: pd.DataFrame, as_of: Optional[pd.Timestamp] = None):
        self.events = validate_membership_events(events)
        seed = self.events.loc[self.events["action"] == "seed"]
        if seed.empty:
            raise ValueError("membership events require seed rows for the current snapshot")
        self.as_of = as_of or pd.Timestamp(seed["effective_date"].max())
        self._current = frozenset(seed["symbol"])
        self._cache: dict[pd.Timestamp, frozenset[str]] = {}

    def status(self) -> dict:
        return research_status(historical_membership=True)

    def symbols_on(self, date: pd.Timestamp) -> frozenset[str]:
        date = pd.Timestamp(date).normalize()
        if date in self._cache:
            return self._cache[date]
        if date >= self.as_of.normalize():
            result = self._current
            self._cache[date] = result
            return result
        members = set(self._current)
        future = self.events[
            self.events["action"].isin(["add", "remove"]) & (self.events["effective_date"] > date)
        ].sort_values(["effective_date", "symbol"], ascending=False)
        for row in future.itertuples(index=False):
            if row.action == "add":
                members.discard(row.symbol)
            else:
                members.add(row.symbol)
        result = frozenset(members)
        self._cache[date] = result
        return result

    def all_symbols(self) -> list[str]:
        return sorted(set(self.events["symbol"]))

    def index_exits(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        removals = self.events[
            (self.events["action"] == "remove")
            & (self.events["effective_date"] >= pd.Timestamp(start))
            & (self.events["effective_date"] <= pd.Timestamp(end))
        ]
        return pd.DataFrame(
            [
                {
                    "date": row.effective_date,
                    "symbol": row.symbol,
                    "event": "INDEX_EXIT",
                    "reason": "removed_from_sp500",
                    "delisting_return_status": "UNAVAILABLE",
                }
                for row in removals.itertuples(index=False)
            ]
        )


def _normalize_ticker(value: str) -> str:
    return str(value).strip().replace(".", "-").upper()


def fetch_historical_sp500_events(cache_dir: Path) -> pd.DataFrame:
    """Download Wikipedia current members + change history and freeze locally."""
    import requests

    cache_dir.mkdir(parents=True, exist_ok=True)
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (research; max-effect-vix)"}, timeout=60)
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text))
    constituents = next(frame for frame in tables if "Symbol" in frame.columns)
    current = [_normalize_ticker(symbol) for symbol in constituents["Symbol"].tolist()]
    as_of = pd.Timestamp(datetime.now(timezone.utc).date())
    events: list[dict] = [
        {"effective_date": as_of, "symbol": symbol, "action": "seed", "source": "wikipedia_current"}
        for symbol in current
    ]

    changes = None
    for frame in tables:
        cols = " ".join(str(column).lower() for column in frame.columns)
        if "date" in cols and "added" in cols and "removed" in cols:
            changes = frame.copy()
            break
    if changes is not None:
        if isinstance(changes.columns, pd.MultiIndex):
            changes.columns = [
                "_".join(str(part) for part in col if str(part) != "nan").strip("_") for col in changes.columns
            ]
        date_col = next(column for column in changes.columns if "date" in str(column).lower())
        added_cols = [column for column in changes.columns if "added" in str(column).lower()]
        removed_cols = [column for column in changes.columns if "removed" in str(column).lower()]
        added_col = next((column for column in added_cols if "ticker" in str(column).lower()), added_cols[0] if added_cols else None)
        removed_col = next(
            (column for column in removed_cols if "ticker" in str(column).lower()),
            removed_cols[0] if removed_cols else None,
        )
        for _, row in changes.iterrows():
            effective = pd.to_datetime(row[date_col], errors="coerce")
            if pd.isna(effective):
                continue
            if added_col is not None and pd.notna(row.get(added_col)) and str(row[added_col]).strip() not in {"", "nan"}:
                # Wikipedia Added column can contain company name; ticker often adjacent.
                token = str(row[added_col]).split()[0] if " " in str(row[added_col]) else str(row[added_col])
                # Prefer explicit ticker column values which are usually short codes.
                if len(token) <= 6 or added_col.lower().endswith("ticker") or "ticker" in added_col.lower():
                    events.append(
                        {
                            "effective_date": effective,
                            "symbol": _normalize_ticker(token),
                            "action": "add",
                            "source": "wikipedia_changes",
                        }
                    )
            if removed_col is not None and pd.notna(row.get(removed_col)) and str(row[removed_col]).strip() not in {"", "nan"}:
                token = str(row[removed_col]).split()[0] if " " in str(row[removed_col]) else str(row[removed_col])
                if len(token) <= 6 or "ticker" in removed_col.lower():
                    events.append(
                        {
                            "effective_date": effective,
                            "symbol": _normalize_ticker(token),
                            "action": "remove",
                            "source": "wikipedia_changes",
                        }
                    )

    frame = validate_membership_events(pd.DataFrame(events))
    path = cache_dir / "sp500_membership_events.parquet"
    frame.to_parquet(path)
    manifest = {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Wikipedia List of S&P 500 companies",
        "DATA_TIER": "HISTORICAL_SP500_APPROX",
        "SURVIVORSHIP_BIAS": "REDUCED_NOT_ELIMINATED",
        "PIT_VALIDATED": False,
        "events": len(frame),
        "current_members": len(current),
        "path": str(path),
        "limitation": "Wikipedia change table is incomplete; index exit != delisting; no CRSP delisting returns.",
    }
    (cache_dir / "sp500_membership_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return frame


def load_historical_provider(cache_dir: Path) -> HistoricalSP500Provider:
    path = cache_dir / "sp500_membership_events.parquet"
    if not path.exists():
        raise FileNotFoundError("Run universe-hist first to cache S&P 500 membership events.")
    return HistoricalSP500Provider(pd.read_parquet(path))


def membership_audit(provider: HistoricalSP500Provider, dates: list[pd.Timestamp]) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "member_count": [len(provider.symbols_on(date)) for date in dates]})
