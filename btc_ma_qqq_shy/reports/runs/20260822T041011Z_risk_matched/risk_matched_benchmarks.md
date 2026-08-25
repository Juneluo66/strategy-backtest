# Risk-Matched Benchmarks

## Judgment: `TIMING_BEATS_RISK_MATCHED_STATIC`

Sample: `2014-11-10` → `2026-08-21`
- Strategy QQQ occupancy: `47.2%`
- Vol-matched static w_QQQ: `0.56`
- Beta-matched static w_QQQ: `0.28` (β_strat=`0.327`)

| Portfolio | CAGR | Sharpe | Vol | MaxDD | Final NAV |
|---|---:|---:|---:|---:|---:|
| BTC_timing_adj_0bps | 17.29% | 1.362 | 12.29% | -16.24% | 6.540 |
| BTC_timing_close_open_costRT_13bps | 13.77% | 1.162 | 11.72% | -13.58% | 4.566 |
| 100pct_QQQ | 18.82% | 0.902 | 21.86% | -35.12% | 7.622 |
| 100pct_SHY | 1.57% | 1.044 | 1.50% | -5.71% | 1.201 |
| static_0.47_QQQ_0.53_SHY | 10.04% | 0.982 | 10.32% | -19.79% | 3.085 |
| vol_matched_wQQQ=0.56 | 11.56% | 0.959 | 12.23% | -22.43% | 3.626 |
| beta_matched_wQQQ=0.28 | 6.65% | 1.077 | 6.17% | -13.91% | 2.134 |

- vs occupancy static: ΔCAGR `7.25` pp, ΔSharpe `0.380`
- vs vol-matched static: ΔCAGR `5.73` pp, ΔSharpe `0.403`

100% QQQ is not a fair risk peer when the strategy spends ~half the time in SHY.
