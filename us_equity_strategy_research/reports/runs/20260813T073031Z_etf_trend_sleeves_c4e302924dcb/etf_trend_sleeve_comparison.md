# ETF Trend Sleeve Experiments

- Common interval: `2006-02-01` → `2026-08-10`
- Cash: `BIL` (not SGOV; avoids H4 inception hole)
- Cost: `5.0` bp one-way
- return_basis: `Yahoo_AdjClose_scaled_Open`
- Frozen D+C hash check: `{'config_hash': '8725aaf1874386e68016e9e7ad290f09b8528a34ecf7857f350acfa8a208b1c2', 'matches_known_freeze': True, 'prefix_ok': True, 'ok': True}`
- Run dir: `/home/ec2-user/strategy-backtest/us_equity_strategy_research/reports/runs/20260813T073031Z_etf_trend_sleeves_c4e302924dcb`

## Rules (frozen for this experiment)

1. **rotation_12_1**: month-end 12-1 momentum; keep only ETFs above 10-month SMA; buy top-2 EW; residual → BIL; next session open.
2. **spy_qqq_protect**: 70% SPY + 30% QQQ; each leg below 10m SMA → that weight to BIL; next open.
3. **f3_rot70_spy30_protect**: 70% rotation sleeve + 30% SPY; only the SPY 30% is SMA-gated to BIL.

## Net results (common interval vs VTI)

| name | net_cagr | net_sharpe | net_max_drawdown | ann_turnover |
|---|---:|---:|---:|---:|
| rotation_12_1 | 0.0991 | 0.5912 | -0.2972 | 4.264092728485657 |
| spy_qqq_protect | 0.0946 | 0.7509 | -0.2050 | 1.691017344896598 |
| f3_rot70_spy30_protect | 0.0966 | 0.6545 | -0.2424 | 3.4600066711140753 |
| vti_bh | 0.1112 | 0.6390 | -0.5545 | 0.0 |
| spy_bh | 0.1122 | 0.6482 | -0.5519 | 0.0 |
| frozen_80_20_spy_dc | 0.1125 | 0.7150 | -0.4617 | 0.0 |
| dc | 0.1002 | 0.7639 | -0.1797 | 0.0 |

## Versus frozen 80% SPY + 20% D+C

- **rotation_12_1**: CAGR edge `-0.0134`, Sharpe edge `-0.1239`, MaxDD edge `+0.1644` (positive MaxDD edge = shallower drawdown).
- **spy_qqq_protect**: CAGR edge `-0.0179`, Sharpe edge `+0.0359`, MaxDD edge `+0.2567` (positive MaxDD edge = shallower drawdown).
- **f3_rot70_spy30_protect**: CAGR edge `-0.0159`, Sharpe edge `-0.0606`, MaxDD edge `+0.2193` (positive MaxDD edge = shallower drawdown).

### Interpretation

- These are price-only ETF rules; data gap risk is low vs equity multifactor/PEAD.
- Do **not** retune the frozen D+C 80/20 on these results.
- Prefer a challenger only if it improves risk-adjusted outcomes without relying on a single subperiod.

