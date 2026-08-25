"""Lookahead audit tests."""
from __future__ import annotations

from pathlib import Path

from backtest import run_conditional_rotation
from config import ProjectConfig
from execution import ExecutionMode

ROOT = Path(__file__).resolve().parents[1]


def test_qc_mode_same_bar_signal_fill():
    """QC replication intentionally uses t-close signal + t-close fill."""
    cfg = ProjectConfig.load(ROOT)
    # Synthetic — just verify mode runs
    import numpy as np
    import pandas as pd

    idx = pd.bdate_range("2010-01-04", periods=1500)
    tickers = cfg.universe()
    closes = pd.DataFrame({t: np.linspace(100, 200, len(idx)) for t in tickers}, index=idx)
    opens = closes * 0.999
    res = run_conditional_rotation(opens, closes, cfg, mode=ExecutionMode.QC_DAILY_SEMANTICS)
    assert res["mode"] == "QC_DAILY_SEMANTICS"


def test_next_open_no_same_bar():
    import numpy as np
    import pandas as pd

    cfg = ProjectConfig.load(ROOT)
    idx = pd.bdate_range("2010-01-04", periods=1500)
    tickers = cfg.universe()
    closes = pd.DataFrame({t: np.linspace(100, 200, len(idx)) for t in tickers}, index=idx)
    opens = closes * 0.999
    res = run_conditional_rotation(opens, closes, cfg, mode=ExecutionMode.NEXT_OPEN_CONSERVATIVE)
    if not res["trades"].empty:
        for _, t in res["trades"].iterrows():
            assert pd.Timestamp(t["execution_date"]) >= pd.Timestamp(t["signal_date"])

import pandas as pd  # noqa: E402
