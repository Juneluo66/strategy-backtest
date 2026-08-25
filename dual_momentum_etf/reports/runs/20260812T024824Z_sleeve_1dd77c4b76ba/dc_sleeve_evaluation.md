# D+C as SPY Defensive Sleeve Evaluation

- Frozen D+C: `attribution_DC` (rules unchanged)
- Sample: `2005-03-01` → `2026-08-10`
- config_hash: `1dd77c4b76bad4fe005e3cec2bf8f3a84471850055c58fc7f1afe6f246993043`
- Weights are **pre-declared scenarios**, not Sharpe-optimized.

## Verdict

- Suitable as SPY defensive sleeve (modest DD cut without extreme lag): **YES**
- Suitable for small-capital long-term growth core: **YES**
- A modest D+C sleeve can cut MaxDD without 100% D+C's extreme opportunity cost; acceptable as a defensive overlay if growth target tolerates small CAGR drag.

- 20% D+C: MaxDD cut 8.51% vs SPY; CAGR lag 0.14%; rel underwater 210m (ongoing)
- 40% D+C: MaxDD cut 17.66% vs SPY; CAGR lag 0.37%; rel underwater 210m (ongoing)

## Monthly rebalance — core metrics

| Portfolio | CAGR | Vol | Sharpe | Sortino | MaxDD | Worst12M | Worst36M | Calmar | $10k end |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100% SPY | 11.09% | 18.98% | 0.65 | 1.01 | -55.19% | -47.35% | -43.46% | 0.20 | 94970 |
| 100% D+C | 9.56% | 13.44% | 0.75 | 1.14 | -17.97% | -10.91% | -4.05% | 0.53 | 70664 |
| 80/20 SPY/D+C | 10.94% | 16.52% | 0.71 | 1.11 | -46.68% | -40.13% | -30.65% | 0.23 | 92401 |
| 60/40 SPY/D+C | 10.72% | 14.59% | 0.77 | 1.20 | -37.53% | -32.18% | -15.69% | 0.29 | 88472 |
| 40/60 SPY/D+C | 10.41% | 13.37% | 0.81 | 1.26 | -27.14% | -23.46% | -8.68% | 0.38 | 83379 |
| 60/40 SPY/IEF | 8.43% | 10.91% | 0.80 | 1.26 | -31.53% | -27.47% | -18.17% | 0.27 | 56606 |

## vs 100% SPY — relative opportunity cost (Metric C style)

| Portfolio | Max rel DD | Longest underwater | Ongoing? | 3y win | 5y win | 10y win |
|---|---:|---:|---|---:|---:|---:|
| 100% SPY | 0.00% | Nonem | no | 0.00% | 0.00% | 0.00% |
| 100% D+C | -73.37% | 210m | yes | 23.42% | 19.70% | 20.29% |
| 80/20 SPY/D+C | -21.83% | 210m | yes | 25.68% | 21.72% | 22.46% |
| 60/40 SPY/D+C | -39.45% | 210m | yes | 25.68% | 21.72% | 21.74% |
| 40/60 SPY/D+C | -53.53% | 210m | yes | 25.23% | 21.72% | 21.74% |

## MaxDD improvement vs CAGR sacrifice (vs 100% SPY)

| Portfolio | MaxDD | DD reduction | CAGR sacrifice | CAGR cost per 1pp DD |
|---|---:|---:|---:|---:|
| 100% SPY | -55.19% | 0.00% | 0.00% | n/a |
| 100% D+C | -17.97% | 37.22% | 1.52% | 0.00 |
| 80/20 SPY/D+C | -46.68% | 8.51% | 0.14% | 0.00 |
| 60/40 SPY/D+C | -37.53% | 17.66% | 0.37% | 0.00 |
| 40/60 SPY/D+C | -27.14% | 28.05% | 0.67% | 0.00 |

## Look-through exposures (monthly blend)

| Portfolio | Equity | Bond | Gold | Cash | LT SPY | LT QQQ | LT SPY+QQQ |
|---|---:|---:|---:|---:|---:|---:|---:|
| 100% SPY | 100.00% | 0.00% | 0.00% | 0.00% | 100.00% | 0.00% | 100.00% |
| 100% D+C | 222.50% | 46.28% | 47.84% | 72.20% | 46.47% | 44.75% | 91.21% |
| 80/20 SPY/D+C | 124.51% | 9.26% | 9.57% | 14.44% | 89.29% | 8.95% | 98.25% |
| 60/40 SPY/D+C | 149.01% | 18.52% | 19.14% | 28.88% | 78.59% | 17.90% | 96.49% |
| 40/60 SPY/D+C | 173.50% | 27.77% | 28.70% | 43.32% | 67.89% | 26.85% | 94.74% |
- Overlap note: outer SPY plus D+C internal SPY/QQQ creates **stacked US equity** look-through; 80/20 is not '80% equity / 20% diversifiers'.

## Stress windows (total return)

| Portfolio | 2000–02 | GFC 2008 | COVID 2020 | 2022 |
|---|---:|---:|---:|---:|
| 100% SPY | n/a (pre-sample) | -45.96% | -9.18% | -18.18% |
| 100% D+C | n/a (pre-sample) | 9.05% | -7.80% | -4.95% |
| 80/20 SPY/D+C | n/a (pre-sample) | -37.28% | -8.69% | -15.36% |
| 60/40 SPY/D+C | n/a (pre-sample) | -27.54% | -8.30% | -12.62% |
| 40/60 SPY/D+C | n/a (pre-sample) | -16.62% | -8.02% | -9.96% |
| 60/40 SPY/IEF | n/a (pre-sample) | -22.75% | -2.14% | -16.38% |

## Calendar year returns

| Year | 100% SPY | 100% D+C | 80/20 SPY/D+C | 60/40 SPY/D+C |
|---|---:|---:|---:|---:|
| 2005 | 5.04% | 0.00% | 4.05% | 3.06% |
| 2006 | 15.85% | 11.22% | 14.99% | 14.10% |
| 2007 | 5.15% | 31.20% | 10.03% | 15.07% |
| 2008 | -36.79% | 2.21% | -29.99% | -22.70% |
| 2009 | 26.35% | 1.05% | 21.24% | 16.13% |
| 2010 | 15.06% | 6.43% | 13.41% | 11.73% |
| 2011 | 1.89% | 11.50% | 3.97% | 5.98% |
| 2012 | 15.99% | 0.65% | 12.81% | 9.68% |
| 2013 | 32.31% | 26.61% | 31.17% | 30.03% |
| 2014 | 13.46% | 6.91% | 12.13% | 10.82% |
| 2015 | 1.23% | -3.95% | 0.27% | -0.74% |
| 2016 | 12.00% | -1.10% | 9.34% | 6.69% |
| 2017 | 21.71% | 18.05% | 20.99% | 20.27% |
| 2018 | -4.57% | 1.58% | -3.28% | -2.02% |
| 2019 | 31.22% | 8.27% | 26.44% | 21.75% |
| 2020 | 18.33% | 26.94% | 20.32% | 22.19% |
| 2021 | 28.73% | 11.49% | 25.14% | 21.63% |
| 2022 | -18.18% | -4.95% | -15.36% | -12.62% |
| 2023 | 26.18% | -1.50% | 20.21% | 14.47% |
| 2024 | 24.89% | 16.28% | 23.15% | 21.42% |
| 2025 | 17.72% | 35.10% | 21.19% | 24.66% |
| 2026 | 13.96% | 12.97% | 13.94% | 13.83% |

## Cost sensitivity (monthly rebalance)

| bps | Portfolio | CAGR | Sharpe | MaxDD | Ann. turnover |
|---:|---|---:|---:|---:|---:|
| 5 | 100% SPY | 11.09% | 0.65 | -55.19% | 0.00 |
| 5 | 100% D+C | 9.56% | 0.75 | -17.97% | 0.00 |
| 5 | 80/20 SPY/D+C | 10.94% | 0.71 | -46.68% | 0.05 |
| 5 | 60/40 SPY/D+C | 10.72% | 0.77 | -37.53% | 0.08 |
| 5 | 40/60 SPY/D+C | 10.41% | 0.81 | -27.14% | 0.08 |
| 10 | 100% SPY | 11.09% | 0.65 | -55.19% | 0.00 |
| 10 | 100% D+C | 9.18% | 0.72 | -17.97% | 0.00 |
| 10 | 80/20 SPY/D+C | 10.86% | 0.71 | -46.74% | 0.05 |
| 10 | 60/40 SPY/D+C | 10.56% | 0.76 | -37.65% | 0.08 |
| 10 | 40/60 SPY/D+C | 10.17% | 0.79 | -27.33% | 0.08 |
| 20 | 100% SPY | 11.09% | 0.65 | -55.19% | 0.00 |
| 20 | 100% D+C | 8.42% | 0.67 | -17.97% | 0.00 |
| 20 | 80/20 SPY/D+C | 10.70% | 0.70 | -46.84% | 0.05 |
| 20 | 60/40 SPY/D+C | 10.23% | 0.74 | -37.89% | 0.08 |
| 20 | 40/60 SPY/D+C | 9.70% | 0.76 | -27.72% | 0.08 |

## Monthly vs annual rebalance turnover

| Portfolio | Monthly ann. TO | Annual ann. TO |
|---|---:|---:|
| 100% SPY | 0.00 | 0.00 |
| 100% D+C | 0.00 | 0.00 |
| 80/20 SPY/D+C | 0.05 | 0.02 |
| 60/40 SPY/D+C | 0.08 | 0.03 |
| 40/60 SPY/D+C | 0.08 | 0.03 |

## Annual rebalance — key metrics (robustness)

| Portfolio | CAGR | Sharpe | MaxDD | Calmar |
|---|---:|---:|---:|---:|
| 100% SPY | 11.09% | 0.65 | -55.19% | 0.20 |
| 100% D+C | 9.56% | 0.75 | -17.97% | 0.53 |
| 80/20 SPY/D+C | 11.02% | 0.72 | -45.66% | 0.24 |
| 60/40 SPY/D+C | 10.83% | 0.79 | -35.90% | 0.30 |
| 40/60 SPY/D+C | 10.51% | 0.82 | -25.37% | 0.41 |

## Interpretation rules applied

- Did **not** pick weights by highest Sharpe.
- Asked whether 20% or 40% D+C can cut MaxDD without 100% D+C's ~210m relative underwater.
- If blends still chronically lag SPY on relative NAV, reject for small-capital growth mandate.

