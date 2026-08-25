# Dual Momentum ETF Summary

Pre-declared variants. Metrics are net of stated one-way costs unless labeled gross.

| Variant | Net CAGR | Net Vol | Net Sharpe | MaxDD | Ann. Turnover | QQQ held% | SPY+QQQ cohold% | vs SPY Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline_6 | 8.85% | 14.65% | 0.65 | -22.81% | 2.77 | 60.9% | 22.7% | 0.65 |
| A_vol_adj | 10.14% | 14.33% | 0.75 | -22.67% | 2.53 | 52.4% | 30.9% | 0.65 |
| B_regime_size | 7.97% | 16.75% | 0.54 | -34.69% | 2.98 | 58.4% | 22.7% | 0.65 |
| C_trend_consistency | 9.38% | 13.23% | 0.74 | -23.19% | 3.00 | 61.8% | 22.5% | 0.65 |
| D_category_only | 9.50% | 14.81% | 0.69 | -22.93% | 3.28 | 46.0% | nan% | 0.65 |
| own_v1 | 8.58% | 13.43% | 0.68 | -22.93% | 3.40 | 35.6% | nan% | 0.65 |

## Notes

- one_way_bps=5.0
- Signal at month-end close; execution at next session open.
- Cash sleeve: SGOV with BIL proxy before SGOV availability.
- No leverage, no shorting.
