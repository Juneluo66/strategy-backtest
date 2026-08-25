# Dual Momentum ETF Summary

Pre-declared variants. Metrics are net of stated one-way costs unless labeled gross.

| Variant | Net CAGR | Net Vol | Net Sharpe | MaxDD | Ann. Turnover | QQQ held% | SPY+QQQ cohold% | vs SPY Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline_6 | 29253.42% | 51.79% | 11.34 | -18.55% | 2.77 | 60.9% | 22.7% | 0.65 |
| A_vol_adj | 45750.42% | 50.90% | 12.43 | -18.37% | 2.53 | 52.4% | 30.9% | 0.65 |
| B_regime_size | 16671.67% | 54.78% | 9.71 | -40.18% | 2.98 | 58.4% | 22.7% | 0.65 |
| C_trend_consistency | 36693.09% | 48.40% | 12.58 | -18.55% | 3.00 | 61.8% | 22.5% | 0.65 |
| D_category_only | 13122403.72% | 85.44% | 14.51 | -23.26% | 3.28 | 46.0% | nan% | 0.65 |
| own_v1 | 29454097.30% | 89.56% | 14.83 | -20.17% | 3.40 | 35.6% | nan% | 0.65 |

## Notes

- one_way_bps=5.0
- Signal at month-end close; execution at next session open.
- Cash sleeve: SGOV with BIL proxy before SGOV availability.
- No leverage, no shorting.
