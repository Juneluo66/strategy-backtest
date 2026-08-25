"""SMA indicator tests."""
from __future__ import annotations

import pandas as pd
import pytest

from indicators import simple_sma


def test_sma_200_seed():
    s = pd.Series(range(1, 251), index=pd.bdate_range("2020-01-02", periods=250))
    sma = simple_sma(s, 200)
    assert pd.isna(sma.iloc[198])
    assert sma.iloc[199] == pytest.approx(100.5)  # mean of 1..200
