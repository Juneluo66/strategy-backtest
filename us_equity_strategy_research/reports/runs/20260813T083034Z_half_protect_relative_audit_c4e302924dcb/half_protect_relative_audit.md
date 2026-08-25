# half_protect — Final Benchmark-Relative Audit (Metric C)

## Decision (A / B / C)

**Choice: `C`**

Prior rel_8020_underwater_days=4382 used non-Metric-C arithmetic excess cumprod (final approx wealth <1) instead of formal relative NAV ratio (final wealth >1). Metric fixed; strategy rules unchanged.

- Default paper candidate unchanged: **80% SPY + 20% D+C**
- No further half_protect parameter / exit-ratio tuning
- Do not purchase Sharadar for this line; do not modify IBKR config

## Why 4382 appeared while CAGR was higher

1. Prior `rel_8020_underwater_days` did **not** use formal Metric C (`relative_nav = nav_half / nav_80`, both rebased to 1 at common start).
2. It used `relative_to_benchmark` → `(1 + r_half - r_80).cumprod()`, an arithmetic-excess path.
3. That approx ended at `0.9790` (<1), while Metric C ends at `1.0487` (>1).
4. The `4382` count is **trading days** (daily-index loop), almost the full sample (`n_trading_days=4555`, calendar span `6614` days).
5. Under **Metric C**, half's wealth is above 80/20 on nearly all days (`frac_days_rel>1 = 99.96%`), but opportunity-cost underwater vs its **2009 relative peak** lasts `210` months (ongoing) — same style as the D+C sleeve Metric C reports.

### Alignment checks

- Common start/end: `2008-07-01` → `2026-08-10`
- Both NAVs rebased to 1.0 at common start: `True`
- NaN counts half/80/60: `0` / `0` / `0`
- Legacy final rel vs Metric C: `0.9790` vs `1.0487` (gap `0.0697`)
- First date Metric C rel>1: `2008-07-02`; last: `2026-08-10`
- Cross-above-1 events (sample): `['2008-07-02', '2008-09-09']` (n=`2`)
- Currently underwater vs relative peak (80/20): `True` at `-14.30%` (peak `2009-03-09`)
- Run: `/home/ec2-user/strategy-backtest/us_equity_strategy_research/reports/runs/20260813T083034Z_half_protect_relative_audit_c4e302924dcb`

## Absolute levels (common sample)

| name | CAGR | Sharpe | MaxDD | end NAV |
|---|---:|---:|---:|---:|
| half_protect | 12.33% | 0.8274 | -25.51% | 8.2070 |
| frozen_80_20_spy_dc | 12.00% | 0.7505 | -38.95% | 7.7847 |
| frozen_60_40_spy_dc | 11.45% | 0.8035 | -29.76% | 7.1175 |
| spy_bh | 12.47% | 0.6945 | -47.17% | 8.3965 |

## 1. Metric C relative packs

| vs | final rel wealth | rel CAGR | max rel UW | longest UW trading days | longest UW months (C) | still UW? | dist to rel peak |
|---|---:|---:|---:|---:|---:|---|---:|
| frozen_80_20_spy_dc | 1.0487 | 0.26% | -15.30% | 4382 | 210 | True | -14.30% |
| frozen_60_40_spy_dc | 1.1465 | 0.76% | -16.17% | 1876 | 90 | True | -12.20% |
| spy_bh | 0.9728 | -0.15% | -31.31% | 4382 | 210 | True | -30.75% |

## 2. Rolling 3y / 5y win rates (half vs benchmarks)

- **half vs 80/20 — 3y** (n=61): CAGR win `50.82%`, Sharpe win `47.54%`, MaxDD win `36.07%`, triple `16.39%`
- **half vs 80/20 — 5y** (n=53): CAGR win `43.40%`, Sharpe win `56.60%`, MaxDD win `43.40%`, triple `20.75%`
- **half vs 60/40 — 3y** (n=61): CAGR win `70.49%`, Sharpe win `55.74%`, MaxDD win `24.59%`, triple `13.11%`
- **half vs 60/40 — 5y** (n=53): CAGR win `84.91%`, Sharpe win `54.72%`, MaxDD win `43.40%`, triple `35.85%`

## 3. Fixed cutoffs (always from common start)

| cutoff | half CAGR/Sharpe/MaxDD | 80/20 | 60/40 | final rel vs80 | final rel vs60 |
|---|---|---|---|---:|---:|
| 2015-12-31 | 10.13% / 0.6842 / -25.51% | 8.53% / 0.5331 / -38.95% | 8.28% / 0.5902 / -29.76% | 1.1105 | 1.1293 |
| 2018-12-31 | 9.82% / 0.6946 / -25.51% | 8.54% / 0.5677 / -38.95% | 8.18% / 0.6163 / -29.76% | 1.1255 | 1.1648 |
| 2020-12-31 | 11.67% / 0.7730 / -25.51% | 10.78% / 0.6596 / -38.95% | 10.27% / 0.7085 / -29.76% | 1.0996 | 1.1637 |
| 2022-12-31 | 10.25% / 0.6957 / -25.51% | 9.66% / 0.6075 / -38.95% | 9.26% / 0.6541 / -29.76% | 1.0745 | 1.1333 |
| 2024-12-31 | 12.02% / 0.8076 / -25.51% | 11.05% / 0.6965 / -38.95% | 10.27% / 0.7316 / -29.76% | 1.1490 | 1.2908 |
| latest | 12.33% / 0.8274 / -25.51% | 12.00% / 0.7505 / -38.95% | 11.45% / 0.8035 / -29.76% | 1.0487 | 1.1465 |

## 4. Exclude last 1 / 2 / 3 years (all three recomputed)

- **Exclude last 1y** (end `2025-08-08`): half `12.05%` / `0.8078` / `-25.51%`; 80/20 `11.32%`; 60/40 `10.65%`; CAGR edge vs80 `0.73%`, vs60 `1.40%`; final rel vs80 `1.1131`, vs60 `1.2335`
- **Exclude last 2y** (end `2024-08-09`): half `11.57%` / `0.7803` / `-25.51%`; 80/20 `10.70%`; 60/40 `9.96%`; CAGR edge vs80 `0.88%`, vs60 `1.62%`; final rel vs80 `1.1294`, vs60 `1.2575`
- **Exclude last 3y** (end `2023-08-11`): half `11.11%` / `0.7480` / `-25.51%`; 80/20 `10.16%`; 60/40 `9.50%`; CAGR edge vs80 `0.95%`, vs60 `1.60%`; final rel vs80 `1.1326`, vs60 `1.2385`

## 5. Annual relative returns

- vs 80/20: positive years `52.63%`; best `2009` (`9.36%`); worst `2010` (`-6.68%`); last 3y share of log-rel growth `-162.99%`
- vs 60/40: positive years `52.63%`; best `2009` (`14.47%`); worst `2025` (`-9.02%`); last 3y share of log-rel growth `-56.19%`

### Annual excess table (half − bench)

| year | vs 80/20 | vs 60/40 |
|---:|---:|---:|
| 2008 | 7.89% | 1.39% |
| 2009 | 9.36% | 14.47% |
| 2010 | -6.68% | -4.99% |
| 2011 | -3.32% | -5.32% |
| 2012 | -0.06% | 3.06% |
| 2013 | 2.22% | 3.36% |
| 2014 | 3.08% | 4.40% |
| 2015 | -1.12% | -0.12% |
| 2016 | -2.71% | -0.07% |
| 2017 | 3.95% | 4.67% |
| 2018 | 0.63% | -0.63% |
| 2019 | -6.25% | -1.56% |
| 2020 | 3.34% | 1.48% |
| 2021 | 3.23% | 6.75% |
| 2022 | -4.02% | -6.76% |
| 2023 | 6.23% | 11.97% |
| 2024 | 2.05% | 3.78% |
| 2025 | -5.54% | -9.02% |
| 2026 | -4.96% | -4.85% |

## Disposition after Metric C fix

- After correcting Metric C: evidence supports treating half as an **independent DEFENSIVE_SHADOW research track** (does **not** replace frozen 60/40); wait for forward evidence.

- **80/20** remains the default paper / IBKR candidate.
- Do **not** retune half_protect; do **not** buy Sharadar; do **not** auto-change IBKR.
