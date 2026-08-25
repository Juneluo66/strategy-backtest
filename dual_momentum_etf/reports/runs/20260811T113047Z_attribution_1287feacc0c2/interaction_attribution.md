# Interaction Attribution

- Common sample start: `2005-03-01`
- Reference (A): `attribution_A` — vol-adjusted dual momentum, **no hysteresis**
- Frozen one-way cost: from config (default 5 bp)
- Regime sizing (B) excluded by design.

## Experiment grid vs A

| Variant | Net CAGR | Sharpe | MaxDD | vs A CAGR | Ann. TO | Cost | Avg QQQ w | Avg SPY w | Avg cash w | Max w | Worst 12M | OOS Sharpe | +year vs A | +roll3y vs A |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 9.73% | 0.72 | -22.67% | 0.00% | 2.78 | 0.06 | 24.03% | 26.55% | 14.53% | 50.00% | -20.95% | 1.63 | n/a | n/a |
| AC | 9.59% | 0.77 | -25.80% | -0.14% | 2.96 | 0.06 | 20.93% | 23.26% | 27.13% | 50.00% | -16.84% | 1.62 | 36.36% | 57.63% |
| AD | 8.71% | 0.69 | -22.93% | -1.02% | 3.48 | 0.07 | 16.47% | 13.57% | 13.37% | 50.00% | -17.01% | 1.59 | 45.45% | 44.84% |
| ACD | 7.84% | 0.67 | -17.84% | -1.88% | 3.69 | 0.08 | 14.53% | 12.21% | 25.39% | 50.00% | -12.13% | 1.62 | 40.91% | 45.97% |
| AD_hyst | 8.61% | 0.68 | -22.93% | -1.12% | 3.38 | 0.07 | 16.47% | 13.76% | 13.37% | 50.00% | -17.01% | 1.61 | 50.00% | 42.91% |
| ACD_hyst | 7.74% | 0.67 | -17.84% | -1.99% | 3.59 | 0.08 | 14.53% | 12.40% | 25.39% | 50.00% | -12.13% | 1.63 | 45.45% | 45.52% |
| DC | 9.56% | 0.75 | -17.97% | -0.17% | 3.48 | 0.07 | 19.19% | 3.10% | 25.39% | 50.00% | -10.91% | 1.52 | 45.45% | 61.44% |

## External benchmarks (same sample)

| Benchmark | Net CAGR | Sharpe | MaxDD | Worst 12M | Notes |
|---|---:|---:|---:|---:|---|
| bh_spy | 11.09% | 0.65 | -55.19% | -47.35% | Buy & hold SPY |
| bh_qqq | 15.72% | 0.78 | -53.40% | -48.00% | Buy & hold QQQ |
| sixty_forty | 8.43% | 0.80 | -31.53% | -27.47% | 60% SPY + 40% IEF, monthly rebalance |
| spy_ma10 | 8.00% | 0.68 | -24.78% | -22.50% | SPY if above 10M SMA else cash |
| simple_dual_mom | 9.46% | 0.69 | -22.81% | -20.95% | Raw dual mom Top2, no vol adj, no hyst |
| ew_trend | 7.37% | 0.55 | -42.35% | -37.49% | Equal-weight risk assets above 10M SMA |

## Stress windows (total return)

| Variant | gfc_2008 | covid_2020 | bear_2022 |
|---|---:|---:|---:|
| attribution_A | -9.36% | -8.50% | -18.92% |
| attribution_AC | 6.98% | -8.50% | -7.17% |
| attribution_AD | -0.32% | -5.18% | -15.61% |
| attribution_ACD | 5.59% | -5.18% | -4.95% |
| attribution_AD_hyst | -0.32% | -5.18% | -15.61% |
| attribution_ACD_hyst | 5.59% | -5.18% | -4.95% |
| attribution_DC | 9.05% | -7.80% | -4.95% |
| bh_spy | -45.96% | -9.18% | -18.18% |
| bh_qqq | -40.65% | 0.14% | -32.58% |
| sixty_forty | -22.75% | -2.14% | -16.38% |
| spy_ma10 | -1.95% | -7.22% | -21.00% |
| simple_dual_mom | -9.36% | -8.50% | -18.92% |
| ew_trend | -28.88% | -4.80% | -18.66% |

## Continue? Positioning check

- A (`attribution_A`) net CAGR 9.73% vs SPY 11.09% vs QQQ 15.72%.
- A MaxDD -22.67% vs SPY -55.19% vs QQQ -53.40%.
- If A lags SPY/QQQ on CAGR but cuts drawdown materially, treat it as a **drawdown-managed allocation** sleeve, not an absolute-return alpha chase.

## Yearly returns (experiments)

See `yearly_returns.csv` and `yearly_delta_vs_A.csv` in this run directory.

