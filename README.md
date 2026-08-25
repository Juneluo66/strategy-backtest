# Strategy Backtest

This directory contains independently runnable strategy projects. Each child
directory owns its data cache, configuration, tests, and documentation.

- `dividend_lowvol_quality/`: A-share high-dividend, low-volatility, and
  quality-filtered portfolio.
- `etf_rotation/`: Research-grade replication of a 49-ETF A-share
  cross-sectional rotation strategy with hysteresis and volatility gating.
- `max_effect_vix/`: Dual-track US-equity MAX research. Default path is
  historical S&P 500 membership approximation (`HISTORICAL_SP500_APPROX`,
  `SURVIVORSHIP_BIAS=REDUCED_NOT_ELIMINATED`, `PIT_VALIDATED=false`).
  Size neutralization remains blocked without PIT market caps.
- `dual_momentum_etf/`: US ETF dual-momentum (month-end / next-open) with
  baseline 6-ETF reference and `own_v1` (category constraint + vol-adjusted
  score + 10-month SMA filter + hysteresis); cash sleeve SGOV with BIL proxy.
- `us_equity_strategy_research/`: US equity multifactor / 12-1 momentum / PEAD
  research vs frozen ETF D+C sleeve. Free-data path keeps `PIT_VALIDATED=false`;
  formal PEAD and PIT fundamentals are gated/BLOCKED when data are insufficient.
- `multi_asset_etf_trend/`: Independent multi-asset absolute-momentum audit
  (SPY/EFA/EEM/IEF/TLT/GLD/DBC/VNQ vs BIL). Pre-registered
  `base_12m_equal` / `ensemble_equal` / `ensemble_risk_balanced` only;
  no link to D+C or half_protect for parameter choice.
- `us_sector_equal_weight/`: Independent US sector **equal-weight rebalancing**
  on the nine 1998 Select Sector SPDRs (`EW9_monthly` / `quarterly` / `annual`).
  Discovery ETF sample is `DISCOVERY_SAMPLE` only; not sector-momentum retuning.
- `us_sector_momentum/`: Independent US sector ETF cross-sectional momentum
  on the nine 1998 Select Sector SPDRs. Pre-registered
  `base_12_1_top3` / `composite_6_1_12_1_top3` / `composite_top3_buffer` only;
  terminal wealth vs SPY is the primary gate (not low drawdown).
- `statistical_signal_validation/`: Cross-project statistical batteries
  (HAC, block bootstrap, PSR/DSR/MinTRL, trial registry incl. failures).
  Does not change strategy parameters or IBKR/production configs.
- `btc_ma_qqq_shy/`: Email-claim audit — weekly BTC >50DMA & 20d momentum
  gate into QQQ else SHY; compare drawdown / risk-adjusted return vs SPY & QQQ
  from 2014 (`DISCOVERY_SAMPLE`).
