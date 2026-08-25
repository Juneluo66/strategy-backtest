# ETF Trend Sleeve Experiments

- Common interval: `2008-06-02` → `2026-08-10`
- Cash: `BIL` (not SGOV; avoids H4 inception hole)
- Cost: `5.0` bp one-way
- return_basis: `Yahoo_AdjClose_scaled_Open`
- Frozen D+C hash check: `{'config_hash': '8725aaf1874386e68016e9e7ad290f09b8528a34ecf7857f350acfa8a208b1c2', 'matches_known_freeze': True, 'prefix_ok': True, 'ok': True}`
- Run dir: `/home/ec2-user/strategy-backtest/us_equity_strategy_research/reports/runs/20260813T073122Z_etf_trend_sleeves_c4e302924dcb`

## Rules (frozen for this experiment)

1. **rotation_12_1**: month-end 12-1 momentum; keep only ETFs above 10-month SMA; buy top-2 EW; residual → BIL; next session open.
2. **spy_qqq_protect**: 70% SPY + 30% QQQ; each leg below 10m SMA → that weight to BIL; next open.
3. **f3_rot70_spy30_protect**: 70% rotation sleeve + 30% SPY; only the SPY 30% is SMA-gated to BIL.

## Net results (common interval vs VTI)

| name | net_cagr | net_sharpe | net_max_drawdown | ann_turnover |
|---|---:|---:|---:|---:|
| rotation_12_1 | 0.0980 | 0.5990 | -0.2972 | 4.343632395002258 |
| spy_qqq_protect | 0.0988 | 0.7734 | -0.2050 | 1.7649443022730695 |
| f3_rot70_spy30_protect | 0.0958 | 0.6638 | -0.2424 | 3.5601290832455224 |
| vti_bh | 0.1179 | 0.6583 | -0.5145 | 0.0 |
| spy_bh | 0.1189 | 0.6674 | -0.5070 | 0.0 |
| frozen_80_20_spy_dc | 0.1165 | 0.7269 | -0.4181 | 0.0 |
| dc | 0.0931 | 0.7498 | -0.1797 | 0.0 |

## Versus frozen 80% SPY + 20% D+C

- **rotation_12_1**: CAGR edge `-0.0186`, Sharpe edge `-0.1279`, MaxDD edge `+0.1209` (positive MaxDD edge = shallower drawdown).
- **spy_qqq_protect**: CAGR edge `-0.0177`, Sharpe edge `+0.0465`, MaxDD edge `+0.2131` (positive MaxDD edge = shallower drawdown).
- **f3_rot70_spy30_protect**: CAGR edge `-0.0207`, Sharpe edge `-0.0631`, MaxDD edge `+0.1757` (positive MaxDD edge = shallower drawdown).

### Interpretation

- These are price-only ETF rules; data gap risk is low vs equity multifactor/PEAD.
- Do **not** retune the frozen D+C 80/20 on these results.
- Prefer a challenger only if it improves risk-adjusted outcomes without relying on a single subperiod.

