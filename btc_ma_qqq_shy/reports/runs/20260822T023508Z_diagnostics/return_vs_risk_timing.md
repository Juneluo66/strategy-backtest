# BTC Gate Diagnostics — Return Timing vs Risk Timing

## Verdict

- **Judgment: `POSSIBLE_INCREMENTAL_RETURN_SIGNAL_NEEDS_TRUE_OOS`**
- Sample: `2014-11-05` → `2026-08-21` (`DISCOVERY_SAMPLE_RESEARCH_CONTAMINATED`)
- Frozen rule under audit: SMA`50` + MOM`20` (do not retune from this report)

## 0. What this answers

Does the BTC Risk-On/Off state forecast **QQQ forward returns**, or mainly **QQQ forward volatility / drawdown risk**?
NAV/Sharpe of the QQQ↔SHY switch is secondary here; ΔR and incremental β after placebos/controls are primary.

## 1. Conditional forward QQQ outcomes given daily BTC Risk-On/Off

| k | E[R\|ON] | E[R\|OFF] | ΔR | Vol ON | Vol OFF | ΔVol | DVol ON | DVol OFF |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| 5 | 0.56% | 0.22% | 0.34% | 15.49% | 20.77% | -5.27% | 7.79% | 11.12% |
| 10 | 1.19% | 0.37% | 0.82% | 16.30% | 21.34% | -5.03% | 8.78% | 12.06% |
| 20 | 2.05% | 1.03% | 1.02% | 17.19% | 21.39% | -4.19% | 9.83% | 12.34% |
| 60 | 4.87% | 4.42% | 0.45% | 18.93% | 21.07% | -2.14% | 11.46% | 12.49% |

At k=20: ΔR=`1.02%`, ΔVol=`-4.19%` (negative ΔVol = ON has lower forward vol).

## 2. Predictive regression (Newey-West HAC)

### Univariate: R_QQQ(t+1:t+k) = α + β BTCSignal_t + ε

- k=1: β=0.00104  t=2.19  p=0.028  n=2964  NW-lags=1
- k=5: β=0.00344  t=1.98  p=0.048  n=2960  NW-lags=5
- k=10: β=0.00816  t=2.65  p=0.008  n=2955  NW-lags=10
- k=20: β=0.01018  t=1.97  p=0.049  n=2945  NW-lags=20
- k=60: β=0.00448  t=0.44  p=0.663  n=2905  NW-lags=60

### Control QQQ own trend: + β2 QQQTrend_t

- k=1: BTC β=0.00110  t=2.38  p=0.018  n=2964  NW-lags=1 ; QQQTrend β=-0.00025  t=-0.46  p=0.648  n=2964  NW-lags=1
- k=5: BTC β=0.00375  t=2.21  p=0.027  n=2960  NW-lags=5 ; QQQTrend β=-0.00138  t=-0.67  p=0.503  n=2960  NW-lags=5
- k=10: BTC β=0.00912  t=3.01  p=0.003  n=2955  NW-lags=10 ; QQQTrend β=-0.00425  t=-1.20  p=0.232  n=2955  NW-lags=10
- k=20: BTC β=0.01315  t=2.59  p=0.010  n=2945  NW-lags=20 ; QQQTrend β=-0.01308  t=-2.19  p=0.028  n=2945  NW-lags=20
- k=60: BTC β=0.01219  t=1.29  p=0.197  n=2905  NW-lags=60 ; QQQTrend β=-0.03332  t=-2.72  p=0.007  n=2905  NW-lags=60

### Full controls: + QQQTrend + SPYTrend + VIX z-score

- k=1: BTC β=0.00136  t=3.00  p=0.003  n=2964  NW-lags=1 ; QQQ β=0.00122  t=1.74  p=0.081  n=2964  NW-lags=1 ; SPY β=-0.00086  t=-1.18  p=0.236  n=2964  NW-lags=1 ; VIX β=0.00107  t=2.31  p=0.021  n=2964  NW-lags=1
- k=5: BTC β=0.00455  t=2.74  p=0.006  n=2960  NW-lags=5 ; QQQ β=0.00258  t=1.16  p=0.247  n=2960  NW-lags=5 ; SPY β=-0.00151  t=-0.67  p=0.501  n=2960  NW-lags=5 ; VIX β=0.00365  t=2.30  p=0.021  n=2960  NW-lags=5
- k=10: BTC β=0.01052  t=3.53  p=0.000  n=2955  NW-lags=10 ; QQQ β=0.00168  t=0.47  p=0.640  n=2955  NW-lags=10 ; SPY β=-0.00044  t=-0.12  p=0.905  n=2955  NW-lags=10 ; VIX β=0.00713  t=2.95  p=0.003  n=2955  NW-lags=10
- k=20: BTC β=0.01561  t=3.07  p=0.002  n=2945  NW-lags=20 ; QQQ β=-0.00358  t=-0.61  p=0.541  n=2945  NW-lags=20 ; SPY β=0.00187  t=0.29  p=0.775  n=2945  NW-lags=20 ; VIX β=0.01370  t=3.91  p=0.000  n=2945  NW-lags=20
- k=60: BTC β=0.01839  t=1.94  p=0.052  n=2905  NW-lags=60 ; QQQ β=-0.00215  t=-0.17  p=0.867  n=2905  NW-lags=60 ; SPY β=-0.01152  t=-0.99  p=0.322  n=2905  NW-lags=60 ; VIX β=0.02823  t=2.76  p=0.006  n=2905  NW-lags=60

### Direct risk-timing regressions

- |R_QQQ_{t+1}|: β=-0.00284  t=-5.51  p=0.000  n=2964  NW-lags=5
- RV_QQQ_{t+1:t+20}: β=-0.04194  t=-3.62  p=0.000  n=2945  NW-lags=20

Key k=20: univ t=`1.97`; after QQQ trend t=`2.59`; after full controls t=`3.07`.

## 3. Lead-lag: Corr(R_BTC_{t-k}, R_QQQ_t)

| k | corr | role |
|---:|---:|---|
| -20 | -0.002 | QQQ_leads |
| -10 | -0.014 | QQQ_leads |
| -5 | 0.025 | QQQ_leads |
| -1 | -0.025 | QQQ_leads |
| 0 | 0.235 | contemporaneous |
| 1 | -0.025 | BTC_leads |
| 5 | 0.003 | BTC_leads |
| 10 | -0.020 | BTC_leads |
| 20 | -0.014 | BTC_leads |

## 4. Placebo gates (same SMA50/MOM20 → QQQ else SHY; only signal asset changes)

| Signal asset | Sharpe | CAGR | Vol | MaxDD | %QQQ |
|---|---:|---:|---:|---:|---:|
| BTC-USD | 1.220 | 15.03% | 12.11% | -16.24% | 47.35% |
| QQQ | 0.889 | 11.14% | 12.76% | -19.12% | 62.37% |
| SPY | 0.641 | 7.97% | 13.25% | -23.66% | 64.35% |
| IWM | 0.745 | 8.67% | 12.09% | -18.99% | 53.46% |
| SOXX | 0.849 | 10.64% | 12.84% | -23.08% | 59.85% |

If BTC ≈ QQQ/SPY/IWM/SOXX placebos, BTC is not special — it is a generic trend/risk filter.

## 5. Yearly active return (strategy − QQQ)

| Year | Σ active | Strat year | QQQ year | Strat Sharpe | QQQ Sharpe |
|---:|---:|---:|---:|---:|---:|
| 2014 | -4.94% | -2.61% | 2.23% | -2.512 | 1.209 |
| 2015 | -1.67% | 8.75% | 9.44% | 0.850 | 0.594 |
| 2016 | 1.62% | 9.56% | 7.10% | 0.857 | 0.505 |
| 2017 | -8.11% | 22.43% | 32.66% | 2.177 | 2.804 |
| 2018 | 2.54% | 4.92% | -0.13% | 0.758 | 0.109 |
| 2019 | -20.80% | 13.79% | 38.96% | 1.325 | 2.114 |
| 2020 | -23.30% | 23.46% | 48.41% | 1.292 | 1.284 |
| 2021 | -8.99% | 17.32% | 27.42% | 1.237 | 1.422 |
| 2022 | 37.37% | 2.18% | -32.58% | 0.224 | -1.070 |
| 2023 | -12.99% | 36.99% | 54.86% | 2.472 | 2.558 |
| 2024 | -13.91% | 10.04% | 25.58% | 0.771 | 1.355 |
| 2025 | -2.15% | 20.79% | 20.77% | 1.850 | 0.923 |
| 2026 | -3.13% | 14.00% | 16.41% | 1.835 | 1.222 |

## 6. Leave-one-crisis-out (Sharpe)

| Removed | Strat Sharpe | QQQ Sharpe | Strat MaxDD |
|---|---:|---:|---:|
| 2018Q4 `['2018-10-01', '2018-12-31']` | 1.247 | 1.005 | -16.24% |
| 2020_COVID `['2020-02-15', '2020-04-30']` | 1.338 | 1.001 | -13.34% |
| 2022_bear `['2022-01-01', '2022-12-31']` | 1.329 | 1.200 | -16.24% |
| drop_best_year_2022 `['2022']` | 1.329 | 1.200 | -16.24% |
| drop_best_63d_active `['2025-01-07', '2025-04-08']` | 1.226 | 1.017 | -16.24% |

## 7. Parameter robustness surface (strategy Sharpe)

Rows = SMA, columns = MOM:

```
mom     5      10     20     40     60
sma                                   
20   1.197  1.137  1.259  1.269  1.020
50   1.374  1.333  1.220  1.231  1.143
100  1.023  1.276  1.165  1.099  0.953
150  0.988  1.151  1.117  0.994  0.917
200  0.991  1.084  1.082  0.956  0.909
```

Frozen 50/20 cell must not be a lone spike; a plateau is healthier.

## 8. Walk-forward slices (contaminated research sample)

> Entire 2014–2026 span was inspected before these splits; treat as **research partitions**, not true locked OOS.

- **discovery_2014_2018** `['2014-11-05', '2018-12-31']`: strat Sharpe `1.051` CAGR `10.10%` MaxDD `-10.94%` | QQQ Sharpe `0.734` CAGR `11.70%`
- **validation_2019_2022** `['2019-01-01', '2022-12-31']`: strat Sharpe `0.999` CAGR `13.95%` MaxDD `-16.24%` | QQQ Sharpe `0.666` CAGR `15.29%`
- **locked_oos_2023_2026** `['2023-01-01', '2026-12-31']`: strat Sharpe `1.693` CAGR `22.25%` MaxDD `-8.62%` | QQQ Sharpe `1.475` CAGR `32.17%`

## 9. Block bootstrap Sharpe (block=21, n=2000)

- Point: strategy `1.220` vs QQQ `0.903` (diff `0.317`)
- Strategy Sharpe 90% band: `[0.776, 1.715]`
- Diff (strat−QQQ) 90% band: `[-0.108, 0.742]` ; P(diff>0)=`89.85%`

## 10. CAPM (caveat: dynamic beta)

- β=0.00040  t=3.24  p=0.001  n=2964  NW-lags=10 (α)
- β=0.31704  t=5.49  p=0.000  n=2964  NW-lags=10 (β_mkt)
- Note: rf_approx_0; dynamic_beta_caveat_applies

## Research conclusion (forced distinction)

1. Compare |ΔR| vs |ΔVol| / downside columns in §1.
2. Require univ β_BTC t-stat and **incremental** t-stat after QQQ trend / VIX (§2).
3. Require BTC placebo Sharpe to dominate QQQ/SPY/IWM/SOXX (§4).
4. Check crisis concentration (§5–6) and grid plateau (§7).
5. True forward evidence still required; this file does not unlock production.
