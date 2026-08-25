"""Execution semantics for QuantConnect replication vs conservative next-open."""
from __future__ import annotations

from enum import Enum


class ExecutionMode(str, Enum):
    QC_DAILY_SEMANTICS = "QC_DAILY_SEMANTICS"
    NEXT_OPEN_CONSERVATIVE = "NEXT_OPEN_CONSERVATIVE"
    NEXT_CLOSE_RESEARCH = "NEXT_CLOSE_RESEARCH"


EXECUTION_DOCS = {
    ExecutionMode.QC_DAILY_SEMANTICS: {
        "signal_timestamp": "t close (OnData daily bar complete)",
        "indicator_timestamp": "t close (Current.Value includes bar t)",
        "order_timestamp": "t close (SetHoldings in OnData)",
        "fill_timestamp": "t close (daily backtest fill at bar close)",
        "return_attribution": "Day t return on prior holding; switch at t close for t+1",
        "lookahead_note": "Same-bar signal+fill at close — matches QC daily replication",
    },
    ExecutionMode.NEXT_OPEN_CONSERVATIVE: {
        "signal_timestamp": "t close",
        "indicator_timestamp": "t close",
        "order_timestamp": "t+1 open",
        "fill_timestamp": "t+1 open",
        "return_attribution": "Day t full return on prior holding; switch at t+1 open",
        "lookahead_note": "No same-bar fill — realistic delay",
    },
    ExecutionMode.NEXT_CLOSE_RESEARCH: {
        "signal_timestamp": "t close",
        "indicator_timestamp": "t close",
        "order_timestamp": "t+1 close",
        "fill_timestamp": "t+1 close",
        "return_attribution": "Signal t, fill t+1 close",
        "lookahead_note": "Research-only delayed execution",
    },
}
