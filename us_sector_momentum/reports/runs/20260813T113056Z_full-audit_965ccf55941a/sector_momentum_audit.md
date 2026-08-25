# US Sector ETF Momentum — Research Audit

**Verdict:** `REJECTED` (7/16 checks)

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
- Strict common sample (9 sectors + SPY + QQQ): `1999-03-10` → `2026-08-12` (6899 rows)
- Extreme |Adj Close daily ret| > 25% flags: 0
- Split-like flags (large raw / small adj): 0
- Manifest retrieved_at_utc: `2026-08-13T11:15:46.916112+00:00`
- File SHA256 recorded for 13 symbols
- Missing returns are **never** `fillna(0)`.

### Risk-free for Sharpe

- Method: `BIL_adj_close_returns_with_IRX_daily_yield_proxy_pre_bil`
- BIL days: 4829; IRX proxy days: 2064
- BIL span: 2007-05-30 → 2026-08-10; IRX span: 1999-03-10 → 2026-08-12

### Per-symbol coverage

| Symbol | Start | End | Rows | Dup | Missing bdys | Ext>25% | Split-like | Inception |
|---|---|---|---:|---:|---:|---:|---:|---|
| XLB | 1998-12-22 | 2026-08-12 | 6951 | 0 | 261 | 0 | 0 | 1998-12-16 |
| XLE | 1998-12-22 | 2026-08-12 | 6951 | 0 | 261 | 0 | 0 | 1998-12-16 |
| XLF | 1998-12-22 | 2026-08-12 | 6951 | 0 | 261 | 0 | 0 | 1998-12-16 |
| XLI | 1998-12-22 | 2026-08-12 | 6951 | 0 | 261 | 0 | 0 | 1998-12-16 |
| XLK | 1998-12-22 | 2026-08-12 | 6951 | 0 | 261 | 0 | 0 | 1998-12-16 |
| XLP | 1998-12-22 | 2026-08-12 | 6951 | 0 | 261 | 0 | 0 | 1998-12-16 |
| XLU | 1998-12-22 | 2026-08-12 | 6951 | 0 | 261 | 0 | 0 | 1998-12-16 |
| XLV | 1998-12-22 | 2026-08-12 | 6951 | 0 | 261 | 0 | 0 | 1998-12-16 |
| XLY | 1998-12-22 | 2026-08-12 | 6951 | 0 | 261 | 0 | 0 | 1998-12-16 |
| SPY | 1998-01-02 | 2026-08-12 | 7196 | 0 | 268 | 0 | 0 | 1993-01-29 |
| QQQ | 1999-03-10 | 2026-08-12 | 6899 | 0 | 257 | 0 | 0 | 1999-03-10 |

## Execution

- Month-end close signal → next session open fill
- One-way cost 5bp; weights drift between rebalances
- No shorts, no leverage, always fully invested in Top 3

## Formal comparison

| strategy | CAGR | Final W | Gross CAGR | Vol | Sharpe(rf) | Sortino | MaxDD | MaxDD days | Calmar | Worst year | Worst 12m | Pos years | Ann turn | Trades/yr | Cost drag | Corr SPY | β SPY | β QQQ | Up cap | Down cap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| spy_buy_hold | 8.30% | 8.18 | 8.30% | 19.19% | 0.418 | 0.649 | -55.19% | 1543.0 | 0.150 | -36.80% | -47.35% | 77.78% | 0.00% | 0.0 | 0.00% | 1.000 | 1.000 | 0.626 | 100.00% | 100.00% |
| qqq_buy_hold | 8.13% | 7.84 | 8.13% | 26.36% | 0.360 | 0.561 | -81.19% | 3611.0 | 0.100 | -46.69% | -69.70% | 77.78% | 0.00% | 0.0 | 0.00% | 0.861 | 1.182 | 1.000 | 123.80% | 124.56% |
| equal_weight_9_monthly | 9.10% | 9.94 | 9.12% | 18.07% | 0.473 | 0.710 | -53.01% | 889.0 | 0.172 | -34.79% | -47.27% | 77.78% | 15.42% | 12.0 | 0.02% | 0.963 | 0.906 | 0.528 | 90.46% | 88.97% |
| base_12_1_top3 | 8.86% | 9.37 | 9.15% | 18.88% | 0.450 | 0.709 | -46.34% | 1026.0 | 0.191 | -29.04% | -40.09% | 77.78% | 270.94% | 12.0 | 0.30% | 0.884 | 0.870 | 0.517 | 90.67% | 89.38% |
| composite_6_1_12_1_top3 | 7.69% | 7.05 | 8.04% | 18.90% | 0.393 | 0.634 | -46.31% | 815.0 | 0.166 | -29.07% | -39.97% | 77.78% | 323.29% | 12.0 | 0.35% | 0.879 | 0.866 | 0.509 | 89.69% | 89.35% |
| composite_top3_buffer | 9.12% | 9.97 | 9.34% | 18.75% | 0.464 | 0.726 | -44.56% | 721.0 | 0.205 | -27.38% | -38.76% | 81.48% | 207.74% | 12.0 | 0.23% | 0.876 | 0.856 | 0.498 | 89.31% | 87.60% |

### Crisis / segment net returns

| Strategy | 2000–02 | 2008 | 2020 | 2022 |
|---|---:|---:|---:|---:|
| spy_buy_hold | -39.15% | -43.90% | -9.18% | -18.18% |
| qqq_buy_hold | -77.74% | -40.49% | 0.14% | -32.58% |
| equal_weight_9_monthly | -22.68% | -41.94% | -12.95% | -5.21% |
| base_12_1_top3 | -24.72% | -36.21% | -9.56% | 9.26% |
| composite_6_1_12_1_top3 | -19.15% | -36.19% | -15.05% | 0.48% |
| composite_top3_buffer | -13.14% | -34.67% | -12.60% | 6.97% |

## Metric C relative wealth

Definition: `relative_nav_t = nav_strategy_t / nav_benchmark_t (both rebased to 1.0 at the first common date). Relative underwater = relative_nav / relative_nav.cummax() - 1. Distance from relative peak = current_relative_drawdown (negative when underwater).`

| Strategy | vs SPY final | vs SPY rel CAGR | vs SPY max UW | vs SPY cur UW | vs QQQ final | vs QQQ rel CAGR | vs EW9 final | vs EW9 rel CAGR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| spy_buy_hold | 1.000 | 0.00% | 0.00% | 0.00% | 0.974 | -0.10% | 0.831 | -0.70% |
| qqq_buy_hold | 1.026 | 0.10% | -65.48% | -5.50% | 1.000 | 0.00% | 0.853 | -0.60% |
| equal_weight_9_monthly | 1.203 | 0.70% | -22.48% | -19.51% | 1.173 | 0.61% | 1.000 | 0.00% |
| base_12_1_top3 | 1.160 | 0.57% | -42.87% | -31.47% | 1.131 | 0.47% | 0.964 | -0.14% |
| composite_6_1_12_1_top3 | 0.876 | -0.50% | -56.57% | -54.66% | 0.853 | -0.60% | 0.728 | -1.20% |
| composite_top3_buffer | 1.239 | 0.81% | -47.76% | -44.59% | 1.207 | 0.72% | 1.029 | 0.11% |

## Is this just tech (XLK)?

**Do not label long-run XLK overweight as sector-momentum alpha.** Results below disclose concentration.

- Challenger XLK hold-month share: 41.64%
- XLK share of positive contribution mass: 24.62%
- XLK share of excess CAGR vs SPY: 34.27%
- Full challenger CAGR: 7.69%
- Exclude-XLK re-run CAGR: 7.90%
- Excess vs SPY (full / ex-XLK): -0.61% / -0.40%
- CAGR when holding XLK / not: 5.88% / 1.75%
- β SPY / β QQQ: 0.866 / 0.509
- vs QQQ final relative NAV / rel CAGR: 0.853 / -0.60%

### Sector hold-month shares (challenger)

| Sector | Hold-month share | Cum contribution | Share of +contrib |
|---|---:|---:|---:|
| XLB | 36.59% | 0.3593 | 14.31% |
| XLE | 35.65% | 0.2544 | 10.14% |
| XLF | 33.75% | 0.1273 | 5.07% |
| XLI | 29.97% | 0.3421 | 13.63% |
| XLK | 41.64% | 0.6181 | 24.62% |
| XLP | 24.61% | 0.1596 | 6.36% |
| XLU | 32.49% | 0.1433 | 5.71% |
| XLV | 29.34% | 0.2122 | 8.45% |
| XLY | 35.96% | 0.2941 | 11.72% |

## Stability (pre-registered)

| Test | CAGR | Final W | Sharpe | MaxDD | Rel CAGR vs SPY |
|---|---:|---:|---:|---:|---:|
| baseline | 7.69% | 7.05 | 0.393 | -46.31% | -0.50% |
| cost_10bp | 7.34% | 6.47 | 0.376 | -46.44% | -0.82% |
| cost_20bp | 6.65% | 5.46 | 0.342 | -46.71% | -1.46% |
| extra_delay | 7.55% | 6.81 | 0.386 | -46.86% | -0.64% |
| exclude_last_1y | 7.75% | 6.63 | 0.398 | -46.31% | 0.01% |
| exclude_last_2y | 7.53% | 5.87 | 0.393 | -46.31% | 0.32% |
| exclude_last_3y | 7.27% | 5.15 | 0.386 | -46.31% | 0.60% |
| restart_2003 | 9.61% | 8.72 | 0.503 | -46.31% | -1.80% |
| restart_2008 | 7.90% | 4.12 | 0.425 | -46.31% | -3.14% |
| restart_2013 | 10.66% | 3.97 | 0.574 | -36.84% | -3.90% |

### Fixed endpoints

| Cutoff | Strat CAGR | SPY CAGR | Beats? | Strat wealth | SPY wealth |
|---|---:|---:|---|---:|---:|
| 2005-12-31 | 6.12% | -1.72% | True | 1.41 | 0.91 |
| 2008-12-31 | 2.24% | -4.05% | True | 1.21 | 0.70 |
| 2012-12-31 | 4.61% | 1.42% | True | 1.78 | 1.20 |
| 2016-12-31 | 6.85% | 4.34% | True | 3.03 | 2.04 |
| 2020-12-31 | 7.46% | 6.48% | True | 4.45 | 3.68 |
| 2024-12-31 | 7.66% | 7.58% | True | 6.22 | 6.10 |
| latest | 7.69% | 8.30% | False | 7.05 | 8.18 |

### Rolling beat rates vs SPY — 5y: 35.55%; 10y: 31.12%

### Leave-one-sector-out (challenger)

| Dropped | CAGR | Final W | MaxDD | Rel CAGR vs SPY |
|---|---:|---:|---:|---:|
| XLB | 8.14% | 7.87 | -43.40% | -0.08% |
| XLE | 7.62% | 6.93 | -42.20% | -0.56% |
| XLF | 8.32% | 8.22 | -45.71% | 0.08% |
| XLI | 7.63% | 6.95 | -44.54% | -0.55% |
| XLK | 7.90% | 7.42 | -46.28% | -0.35% |
| XLP | 9.01% | 9.71 | -50.69% | 0.71% |
| XLU | 9.39% | 10.66 | -46.98% | 1.07% |
| XLV | 8.29% | 8.16 | -48.55% | 0.02% |
| XLY | 8.31% | 8.20 | -45.71% | 0.07% |

### Block bootstrap (CAGR strat − CAGR SPY)

| Version | Observed | Mean | 2.5% | 97.5% | P(diff>0) | Block | N |
|---|---:|---:|---:|---:|---:|---:|---:|
| base_12_1_top3 | 0.56% | 0.62% | -2.43% | 3.87% | 64.00% | 21 | 400 |
| composite_6_1_12_1_top3 | -0.61% | -0.58% | -3.72% | 2.76% | 35.75% | 21 | 400 |
| composite_top3_buffer | 0.82% | 0.83% | -2.16% | 4.06% | 67.50% | 21 | 400 |

Method: moving-block paired bootstrap (not i.i.d. daily).

## Gate checklist

- [ ] `net_cagr_above_spy`
- [ ] `final_wealth_above_spy`
- [ ] `cagr_edge_at_least_~1pp`
- [ ] `rolling_5y_beat_spy_ge_55pct`
- [ ] `rolling_10y_beat_spy_ge_60pct`
- [x] `exclude_last_1y_still_leads_spy`
- [x] `exclude_last_2y_still_leads_spy`
- [x] `exclude_last_3y_still_leads_spy`
- [x] `fixed_cutoffs_majority_lead_spy`
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

Run directory: `/home/ec2-user/strategy-backtest/us_sector_momentum/reports/runs/20260813T113056Z_full-audit_965ccf55941a`

## Outputs

- `reports/sector_momentum_audit.md`
- `reports/sector_momentum_metrics.csv`
- `reports/sector_momentum_rolling.csv`
- `reports/sector_momentum_sector_contributions.csv`
- `reports/sector_momentum_fixed_endpoints.csv`
- `reports/sector_momentum_bootstrap.csv`
