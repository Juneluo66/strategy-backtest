import pandas as pd

from max_effect_vix.status import research_status
from max_effect_vix.universe_provider import HistoricalSP500Provider
from max_effect_vix.validation import fama_macbeth, spearman_ic, summarize_fama_macbeth


def test_historical_status_labels_never_claim_pit_or_eliminated_bias():
    status = research_status(historical_membership=True)
    assert status["DATA_TIER"] == "HISTORICAL_SP500_APPROX"
    assert status["SURVIVORSHIP_BIAS"] == "REDUCED_NOT_ELIMINATED"
    assert status["PIT_VALIDATED"] is False
    assert status["SIZE_NEUTRAL"] == "BLOCKED_BY_PIT_MARKET_CAP"


def test_symbols_on_reverses_future_changes_from_current_seed():
    events = pd.DataFrame(
        [
            {"effective_date": "2024-06-01", "symbol": "AAA", "action": "seed", "source": "test"},
            {"effective_date": "2024-06-01", "symbol": "BBB", "action": "seed", "source": "test"},
            {"effective_date": "2024-06-01", "symbol": "CCC", "action": "seed", "source": "test"},
            {"effective_date": "2024-03-01", "symbol": "DDD", "action": "remove", "source": "test"},
            {"effective_date": "2024-03-01", "symbol": "CCC", "action": "add", "source": "test"},
        ]
    )
    provider = HistoricalSP500Provider(events, as_of=pd.Timestamp("2024-06-01"))
    before = provider.symbols_on(pd.Timestamp("2024-02-01"))
    assert "DDD" in before
    assert "CCC" not in before
    assert "AAA" in before
    after = provider.symbols_on(pd.Timestamp("2024-06-01"))
    assert after == frozenset({"AAA", "BBB", "CCC"})


def test_fama_macbeth_marks_size_blocked():
    dates = pd.bdate_range("2020-01-01", periods=3)
    symbols = [f"S{i}" for i in range(30)]
    signals = pd.DataFrame(
        [[float(i) for i in range(30)] for _ in dates], index=dates, columns=symbols
    )
    forwards = -signals / 100.0
    monthly = fama_macbeth(signals, forwards)
    summary = summarize_fama_macbeth(monthly)
    assert summary["size_status"] == "BLOCKED_BY_PIT_MARKET_CAP"
    assert summary["months"] >= 1
    assert spearman_ic(signals.iloc[0], forwards.iloc[0]) < 0
