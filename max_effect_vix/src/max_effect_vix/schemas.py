"""Column contracts for historical membership and validation artifacts."""
from __future__ import annotations

import pandas as pd

MEMBERSHIP_EVENT_COLUMNS = ["effective_date", "symbol", "action", "source"]
INDEX_EXIT_COLUMNS = ["date", "symbol", "event", "reason", "delisting_return_status"]


def validate_membership_events(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in MEMBERSHIP_EVENT_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"membership events missing columns: {missing}")
    out = frame.copy()
    out["effective_date"] = pd.to_datetime(out["effective_date"])
    out["symbol"] = out["symbol"].astype(str).str.replace(".", "-", regex=False)
    out["action"] = out["action"].str.lower()
    if not set(out["action"]).issubset({"add", "remove", "seed"}):
        raise ValueError("membership action must be add|remove|seed")
    return out.sort_values(["effective_date", "symbol"]).reset_index(drop=True)
