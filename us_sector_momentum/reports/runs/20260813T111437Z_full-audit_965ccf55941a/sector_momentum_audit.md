# US Sector ETF Momentum — Research Audit

**Verdict:** `REJECTED` (3/16 checks)

Reason: CAGR/final wealth did not beat SPY — Sharpe alone cannot pass.

Independent research track. **No** rule inheritance from D+C, 80/20, half_protect, or multi_asset_etf_trend. Primary objective: long-run terminal wealth (not low drawdown / cash).

**IBKR modified:** `false` (must remain false).

## Pre-registered versions (only)

1. `base_12_1_top3` — 12-1 total return, Top 3 equal weight, always 100% invested
2. `composite_6_1_12_1_top3` — **sole return challenger**; 0.5·rank%ile(6-1)+0.5·rank%ile(12-1), Top 3
3. `composite_top3_buffer` — same scores as (2); hold while still in Top 4; fill vacancies by score

Forbidden: Top 1/2/4/5; other lookbacks; vol scaling; SMA; BIL sleeve; XLRE/XLC; leverage.

## Data audit

- Return basis: `Yahoo_AdjClose_scaled_Open`
- Strict common sample (9 sectors + SPY + QQQ): `2005-01-03` → `2026-08-10` (5434 rows)
- Extreme |Adj Close daily ret| > 25% flags: 0
- Split-like flags (large raw / small adj): 0
- Manifest retrieved_at_utc: `2026-08-13T11:03:02.282440+00:00`
- File SHA256 recorded for 13 symbols
- Missing returns are **never** `fillna(0)`.

### Risk-free for Sharpe

- Method: `BIL_adj_close_returns_with_IRX_daily_yield_proxy_pre_bil`
- BIL days: 4829; IRX proxy days: 602
- BIL span: 2007-05-30 → 2026-08-10; IRX span: 2005-01-03 → 2026-08-10

### Per-symbol coverage

| Symbol | Start | End | Rows | Dup | Missing bdys | Ext>25% | Split-like | Inception |
|---|---|---|---:|---:|---:|---:|---:|---|
| XLB | 1998-12-22 | 2026-08-12 | 6951 | 0 | 261 | 0 | 0 | 1998-12-16 |
| XLE | 2005-01-03 | 2026-08-12 | 5436 | 0 | 202 | 0 | 0 | 1998-12-16 |
| XLF | 2005-01-03 | 2026-08-12 | 5436 | 0 | 202 | 0 | 0 | 1998-12-16 |
| XLI | 2005-01-03 | 2026-08-12 | 5436 | 0 | 202 | 0 | 0 | 1998-12-16 |
| XLK | 2005-01-03 | 2026-08-12 | 5436 | 0 | 202 | 0 | 0 | 1998-12-16 |
| XLP | 2005-01-03 | 2026-08-12 | 5436 | 0 | 202 | 0 | 0 | 1998-12-16 |
| XLU | 2005-01-03 | 2026-08-12 | 5436 | 0 | 202 | 0 | 0 | 1998-12-16 |
| XLV | 2005-01-03 | 2026-08-12 | 5436 | 0 | 202 | 0 | 0 | 1998-12-16 |
| XLY | 2005-01-03 | 2026-08-12 | 5436 | 0 | 202 | 0 | 0 | 1998-12-16 |
| SPY | 2005-01-03 | 2026-08-10 | 5434 | 0 | 202 | 0 | 0 | 1993-01-29 |
| QQQ | 2005-01-03 | 2026-08-10 | 5434 | 0 | 202 | 0 | 0 | 1999-03-10 |

## Execution

- Month-end close signal → next session open fill
- One-way cost 5bp; weights drift between rebalances
- No shorts, no leverage, always fully invested in Top 3

## Formal comparison

| strategy | CAGR | Final W | Gross CAGR | Vol | Sharpe(rf) | Sortino | MaxDD | MaxDD days | Calmar | Worst year | Worst 12m | Pos years | Ann turn | Trades/yr | Cost drag | Corr SPY | β SPY | β QQQ | Up cap | Down cap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| spy_buy_hold | 11.20% | 8.83 | 11.20% | 19.27% | 0.564 | 0.792 | -55.19% | 1223.0 | 0.203 | -36.79% | -47.35% | 85.71% | 0.00% | 0.0 | 0.00% | 1.000 | 1.000 | 0.807 | 100.00% | 100.00% |
| qqq_buy_hold | 15.75% | 20.10 | 15.75% | 21.99% | 0.702 | 1.012 | -53.40% | 781.0 | 0.295 | -41.73% | -48.00% | 85.71% | 0.00% | 0.0 | 0.00% | 0.921 | 1.050 | 1.000 | 112.91% | 109.52% |
| equal_weight_9_monthly | 10.54% | 7.82 | 10.56% | 18.42% | 0.549 | 0.765 | -53.01% | 889.0 | 0.199 | -34.79% | -47.27% | 80.95% | 14.86% | 12.0 | 0.02% | 0.972 | 0.929 | 0.715 | 92.05% | 91.86% |
| base_12_1_top3 | 9.80% | 6.81 | 10.09% | 19.11% | 0.500 | 0.737 | -46.34% | 740.0 | 0.211 | -29.04% | -40.09% | 80.95% | 266.77% | 12.0 | 0.29% | 0.898 | 0.891 | 0.714 | 92.08% | 92.52% |
| composite_6_1_12_1_top3 | 7.81% | 4.68 | 8.16% | 19.01% | 0.406 | 0.621 | -46.31% | 680.0 | 0.169 | -29.07% | -39.97% | 80.95% | 324.27% | 12.0 | 0.35% | 0.895 | 0.882 | 0.703 | 90.77% | 92.97% |
| composite_top3_buffer | 9.14% | 6.02 | 9.36% | 19.02% | 0.470 | 0.697 | -44.56% | 721.0 | 0.205 | -27.38% | -38.76% | 85.71% | 199.72% | 12.0 | 0.22% | 0.895 | 0.883 | 0.701 | 91.15% | 92.07% |

### Crisis / segment net returns

| Strategy | 2000–02 | 2008 | 2020 | 2022 |
|---|---:|---:|---:|---:|
| spy_buy_hold | n/a | -43.90% | -9.18% | -18.18% |
| qqq_buy_hold | n/a | -40.49% | 0.14% | -32.58% |
| equal_weight_9_monthly | n/a | -41.94% | -12.95% | -5.21% |
| base_12_1_top3 | n/a | -36.21% | -9.56% | 9.26% |
| composite_6_1_12_1_top3 | n/a | -36.19% | -15.05% | 0.48% |
| composite_top3_buffer | n/a | -34.67% | -12.60% | 6.97% |

## Metric C relative wealth

Definition: `relative_nav_t = nav_strategy_t / nav_benchmark_t (both rebased to 1.0 at the first common date). Relative underwater = relative_nav / relative_nav.cummax() - 1. Distance from relative peak = current_relative_drawdown (negative when underwater).`

| Strategy | vs SPY final | vs SPY rel CAGR | vs SPY max UW | vs SPY cur UW | vs QQQ final | vs QQQ rel CAGR | vs EW9 final | vs EW9 rel CAGR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| spy_buy_hold | 1.000 | 0.00% | 0.00% | 0.00% | 0.438 | -3.95% | 1.122 | 0.56% |
| qqq_buy_hold | 2.284 | 4.11% | -21.11% | -5.93% | 1.000 | 0.00% | 2.562 | 4.69% |
| equal_weight_9_monthly | 0.891 | -0.56% | -22.48% | -19.81% | 0.390 | -4.48% | 1.000 | 0.00% |
| base_12_1_top3 | 0.782 | -1.19% | -42.87% | -32.15% | 0.343 | -5.09% | 0.878 | -0.63% |
| composite_6_1_12_1_top3 | 0.537 | -2.98% | -56.57% | -55.21% | 0.235 | -6.81% | 0.603 | -2.44% |
| composite_top3_buffer | 0.691 | -1.78% | -47.76% | -45.26% | 0.303 | -5.66% | 0.775 | -1.23% |

## Is this just tech (XLK)?

**Do not label long-run XLK overweight as sector-momentum alpha.** Results below disclose concentration.

- Challenger XLK hold-month share: 46.15%
- XLK share of positive contribution mass: 27.69%
- XLK share of excess CAGR vs SPY: 1.38%
- Full challenger CAGR: 7.81%
- Exclude-XLK re-run CAGR: 7.85%
- Excess vs SPY (full / ex-XLK): -3.39% / -3.34%
- CAGR when holding XLK / not: 6.71% / 1.08%
- β SPY / β QQQ: 0.882 / 0.703
- vs QQQ final relative NAV / rel CAGR: 0.235 / -6.81%

### Sector hold-month shares (challenger)

| Sector | Hold-month share | Cum contribution | Share of +contrib |
|---|---:|---:|---:|
| XLB | 30.36% | 0.2496 | 12.40% |
| XLE | 30.77% | -0.0613 | 0.00% |
| XLF | 32.79% | 0.1311 | 6.51% |
| XLI | 34.82% | 0.3194 | 15.87% |
| XLK | 46.15% | 0.5574 | 27.69% |
| XLP | 26.72% | 0.1766 | 8.78% |
| XLU | 30.36% | 0.0621 | 3.08% |
| XLV | 29.55% | 0.2079 | 10.33% |
| XLY | 38.46% | 0.3087 | 15.34% |

## Stability (pre-registered)

| Test | CAGR | Final W | Sharpe | MaxDD | Rel CAGR vs SPY |
|---|---:|---:|---:|---:|---:|
| baseline | 7.81% | 4.68 | 0.406 | -46.31% | -2.98% |
| cost_10bp | 7.46% | 4.38 | 0.389 | -46.44% | -3.29% |
| cost_20bp | 6.76% | 3.83 | 0.355 | -46.71% | -3.91% |
| extra_delay | 7.59% | 4.49 | 0.396 | -46.86% | -3.22% |
| exclude_last_1y | 7.90% | 4.41 | 0.413 | -46.31% | -2.40% |
| exclude_last_2y | 7.67% | 3.93 | 0.410 | -46.31% | -2.14% |
| exclude_last_3y | 7.35% | 3.47 | 0.403 | -46.31% | -1.89% |
| restart_2003 | 7.81% | 4.68 | 0.406 | -46.31% | -2.98% |
| restart_2008 | 7.84% | 4.07 | 0.422 | -46.31% | -3.20% |
| restart_2013 | 10.57% | 3.92 | 0.570 | -36.84% | -3.99% |

### Fixed endpoints

| Cutoff | Strat CAGR | SPY CAGR | Beats? | Strat wealth | SPY wealth |
|---|---:|---:|---|---:|---:|
| 2005-12-31 | n/a | n/a | False | n/a | n/a |
| 2008-12-31 | -6.79% | -9.33% | True | 0.81 | 0.75 |
| 2012-12-31 | 2.58% | 3.77% | False | 1.19 | 1.29 |
| 2016-12-31 | 6.74% | 7.49% | False | 2.04 | 2.20 |
| 2020-12-31 | 7.62% | 9.68% | False | 2.99 | 3.97 |
| 2024-12-31 | 7.84% | 10.48% | False | 4.17 | 6.58 |
| latest | 7.81% | 11.20% | False | 4.68 | 8.83 |

### Rolling beat rates vs SPY — 5y: 11.29%; 10y: 0.00%

### Leave-one-sector-out (challenger)

| Dropped | CAGR | Final W | MaxDD | Rel CAGR vs SPY |
|---|---:|---:|---:|---:|
| XLB | 8.55% | 5.38 | -43.40% | -2.32% |
| XLE | 8.64% | 5.48 | -42.20% | -2.26% |
| XLF | 8.95% | 5.80 | -45.71% | -1.96% |
| XLI | 7.72% | 4.60 | -44.54% | -3.06% |
| XLK | 7.85% | 4.72 | -46.28% | -2.94% |
| XLP | 8.98% | 5.84 | -50.69% | -1.92% |
| XLU | 10.34% | 7.54 | -46.98% | -0.70% |
| XLV | 9.08% | 5.95 | -48.55% | -1.83% |
| XLY | 8.27% | 5.11 | -45.71% | -2.56% |

### Block bootstrap (CAGR strat − CAGR SPY)

| Version | Observed | Mean | 2.5% | 97.5% | P(diff>0) | Block | N |
|---|---:|---:|---:|---:|---:|---:|---:|
| base_12_1_top3 | -1.40% | -1.27% | -5.77% | 2.69% | 23.75% | 21 | 400 |
| composite_6_1_12_1_top3 | -3.40% | -3.29% | -7.34% | 0.67% | 6.25% | 21 | 400 |
| composite_top3_buffer | -2.06% | -1.96% | -6.01% | 2.05% | 14.25% | 21 | 400 |

Method: moving-block paired bootstrap (not i.i.d. daily).

## Gate checklist

- [ ] `net_cagr_above_spy`
- [ ] `final_wealth_above_spy`
- [ ] `cagr_edge_at_least_~1pp`
- [ ] `rolling_5y_beat_spy_ge_55pct`
- [ ] `rolling_10y_beat_spy_ge_60pct`
- [ ] `exclude_last_1y_still_leads_spy`
- [ ] `exclude_last_2y_still_leads_spy`
- [ ] `exclude_last_3y_still_leads_spy`
- [ ] `fixed_cutoffs_majority_lead_spy`
- [ ] `cost_10bp_still_leads_spy`
- [ ] `cost_20bp_still_leads_spy`
- [ ] `delay_does_not_flip`
- [ ] `excess_not_entirely_from_xlk`
- [x] `qqq_results_disclosed`
- [x] `maxdd_not_5pp_deeper_than_spy`
- [x] `no_posthoc_search`

## Decision

**REJECTED.** Do not change Top-N, lookbacks, add SMA/BIL, or modify IBKR. Higher Sharpe with lower terminal wealth than SPY remains a failure.

## Reproduce

```bash
cd /home/ec2-user/strategy-backtest/us_sector_momentum
python3 -m pip install -e '.[dev]'
us-sector-momentum fetch
us-sector-momentum audit-data
us-sector-momentum full-audit
pytest -q
```

Run directory: `/home/ec2-user/strategy-backtest/us_sector_momentum/reports/runs/20260813T111437Z_full-audit_965ccf55941a`

## Outputs

- `reports/sector_momentum_audit.md`
- `reports/sector_momentum_metrics.csv`
- `reports/sector_momentum_rolling.csv`
- `reports/sector_momentum_sector_contributions.csv`
- `reports/sector_momentum_fixed_endpoints.csv`
- `reports/sector_momentum_bootstrap.csv`
