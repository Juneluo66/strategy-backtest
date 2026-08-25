"""Fixed portfolio experiments P0–P5 with qualification gates."""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .status import gate_equity_for_portfolio


def build_portfolios(
    *,
    vti: pd.Series,
    spy: pd.Series,
    dc: pd.Series,
    equity: Optional[pd.Series],
    equity_grade: str,
    equity_is_pead_proxy: bool,
    qual: Optional[pd.Series] = None,
) -> dict[str, pd.Series]:
    out = {}
    out["P0"] = vti
    # P1 frozen 80/20 SPY/D+C
    aligned = pd.concat([spy.rename("spy"), dc.rename("dc")], axis=1).dropna()
    out["P1"] = 0.8 * aligned["spy"] + 0.2 * aligned["dc"]
    qualified = gate_equity_for_portfolio(equity_grade, is_pead_proxy=equity_is_pead_proxy)
    if qualified and equity is not None:
        a = pd.concat([vti.rename("vti"), equity.rename("eq")], axis=1).dropna()
        out["P2"] = 0.8 * a["vti"] + 0.2 * a["eq"]
        b = pd.concat([vti.rename("vti"), dc.rename("dc"), equity.rename("eq")], axis=1).dropna()
        out["P3"] = 0.6 * b["vti"] + 0.2 * b["dc"] + 0.2 * b["eq"]
    else:
        out["P2"] = pd.Series(dtype=float, name="SKIPPED_NO_QUALIFIED_EQUITY")
        out["P3"] = pd.Series(dtype=float, name="SKIPPED_NO_QUALIFIED_EQUITY")
    if qual is not None:
        c = pd.concat([vti.rename("vti"), qual.rename("q"), dc.rename("dc")], axis=1).dropna()
        out["P4"] = 0.7 * c["vti"] + 0.1 * c["q"] + 0.2 * c["dc"]
    else:
        out["P4"] = pd.Series(dtype=float, name="SKIPPED_NO_QUAL")
    out["P5"] = pd.Series(dtype=float, name="SKIPPED_INSUFFICIENT_EVIDENCE")
    # Experiment sleeve — not frozen
    d = pd.concat([vti.rename("vti"), dc.rename("dc")], axis=1).dropna()
    out["EXP_80_20_VTI_DC"] = 0.8 * d["vti"] + 0.2 * d["dc"]
    return out
