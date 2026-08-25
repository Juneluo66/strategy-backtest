"""Backtest engine for BTC-gated QQQ/SHY."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import ProjectConfig
from .data import load_adj_close
from .signals import btc_daily_signal, build_position_series, weekly_decision_dates


def run_backtest(config: ProjectConfig) -> dict:
    prices = load_adj_close(config)
    dcfg = config.raw["data"]
    rcfg = config.raw["rules"]
    btc_sym = dcfg["btc_symbol"]
    risk_on = dcfg["risk_on"]
    risk_off = dcfg["risk_off"]
    audit_start = pd.Timestamp(dcfg["audit_start"])

    feat = btc_daily_signal(
        prices[btc_sym],
        sma_window=int(rcfg["sma_window"]),
        momentum_window=int(rcfg["momentum_window"]),
    )

    # ETF trading calendar: unique intersection of QQQ/SHY/benchmarks
    etf_cols = list(dict.fromkeys([risk_on, risk_off, *dcfg["benchmarks"]]))
    etf = prices[etf_cols].dropna(how="any")
    # Align BTC signal onto ETF calendar via asof (BTC prints daily incl. weekends)
    risk_on_on_etf = feat["risk_on"].reindex(etf.index, method="ffill")

    position = build_position_series(
        risk_on_on_etf,
        etf.index,
        risk_on_asset=risk_on,
        risk_off_asset=risk_off,
    )

    rets = etf.pct_change()
    on_mask = (position == risk_on).to_numpy()
    strat_ret = pd.Series(
        np.where(on_mask, rets[risk_on].to_numpy(), rets[risk_off].to_numpy()),
        index=etf.index,
        name="strategy",
    )
    strat_ret = strat_ret.fillna(0.0)

    # Optional round-trip cost on switches (bps of notional)
    cost_bps = float(rcfg.get("costs_bps_roundtrip", 0))
    switch = position.ne(position.shift(1)) & position.notna()
    switch.iloc[0] = False
    if cost_bps > 0:
        strat_ret = strat_ret - switch.astype(float) * (cost_bps / 10000.0)

    # Effective audit start: max(config, first date with defined BTC risk_on signal)
    first_signal = feat["risk_on"].dropna().index.min()
    btc_raw_start = prices[btc_sym].dropna().index.min()
    effective_start = max(audit_start, pd.Timestamp(first_signal))
    mask = etf.index >= effective_start
    out = {
        "prices": prices,
        "features": feat,
        "etf": etf,
        "position": position,
        "strategy_return": strat_ret,
        "returns_audit": {
            "strategy": strat_ret.loc[mask].iloc[1:],
            "SPY": rets["SPY"].loc[mask].iloc[1:],
            "QQQ": rets[risk_on].loc[mask].iloc[1:],
            "SHY": rets[risk_off].loc[mask].iloc[1:],
        },
        "position_audit": position.loc[mask],
        "weekly_decisions": weekly_decision_dates(etf.index[mask]),
        "audit_start": effective_start,
        "audit_start_requested": audit_start,
        "btc_price_start": pd.Timestamp(btc_raw_start),
        "first_signal_date": pd.Timestamp(first_signal),
        "switch_count_audit": int(switch.loc[mask].sum()),
    }
    return out
