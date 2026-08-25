"""Load formal EW9 equity paths from latest us_sector_equal_weight audit artifacts."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd


MONOREPO = Path(__file__).resolve().parents[3]
EW_ROOT = MONOREPO / "us_sector_equal_weight"


def latest_ew9_run() -> Path:
    runs = sorted((EW_ROOT / "reports" / "runs").glob("*full-audit*"))
    if not runs:
        raise FileNotFoundError("no us_sector_equal_weight full-audit runs found")
    return runs[-1]


def _net_from_equity_csv(path: Path) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    return df["net_return"].astype(float)


def load_ew9_series(run_dir: Optional[Path] = None) -> dict[str, pd.Series]:
    """
    Returns net return series for EW9 versions from saved CSVs, and rebuilds
    controls (SPY, RSP, no-rebalance) via the frozen equal-weight package APIs
    without changing strategy rules.
    """
    run_dir = run_dir or latest_ew9_run()
    out = {
        "EW9_monthly": _net_from_equity_csv(run_dir / "equity_EW9_monthly.csv"),
        "EW9_quarterly": _net_from_equity_csv(run_dir / "equity_EW9_quarterly.csv"),
        "EW9_annual": _net_from_equity_csv(run_dir / "equity_EW9_annual.csv"),
    }

    # Rebuild controls with frozen package (read-only use of APIs)
    from us_sector_equal_weight.config import load_config
    from us_sector_equal_weight.data import load_ohlc, load_rf_daily, strict_common_index
    from us_sector_equal_weight.schedules import (
        run_ew9_version,
        run_no_rebalance_basket,
    )
    from us_sector_equal_weight.backtest import buy_and_hold

    config = load_config(EW_ROOT)
    opens, closes, _ = load_ohlc(config, symbols=list(dict.fromkeys(config.sectors + config.benchmarks)))
    common = strict_common_index(closes[config.panel_symbols])
    opens_c = opens.reindex(common)
    closes_c = closes.reindex(common)

    spy = closes_c["SPY"].pct_change(fill_method=None).dropna()
    out["SPY"] = spy.rename("SPY")

    hold = run_no_rebalance_basket(opens_c, closes_c, one_way_bps=config.one_way_bps)
    out["no_rebalance_basket"] = hold["equity"]["net_return"].rename("no_rebalance_basket")

    if "RSP" in closes.columns and closes["RSP"].notna().any():
        rsp_idx = closes.index[closes[config.sectors + ["RSP"]].notna().all(axis=1)]
        rsp = closes.loc[rsp_idx, "RSP"].pct_change(fill_method=None).dropna()
        out["RSP"] = rsp.rename("RSP")
        # EW monthly on RSP span for fair comparison
        ew_span = run_ew9_version(
            opens.reindex(rsp_idx),
            closes.reindex(rsp_idx),
            "EW9_monthly",
            one_way_bps=config.one_way_bps,
        )
        out["EW9_monthly_on_rsp_span"] = ew_span["equity"]["net_return"].rename("EW9_monthly_on_rsp_span")
    else:
        out["RSP"] = pd.Series(dtype=float)

    out["_meta"] = {  # type: ignore
        "run_dir": str(run_dir),
        "discovery_start": str(common.min().date()),
        "discovery_end": str(common.max().date()),
        "sample_label": "DISCOVERY_SAMPLE",
    }
    return out
