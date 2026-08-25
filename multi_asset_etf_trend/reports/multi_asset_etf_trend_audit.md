# Multi-Asset ETF Trend Strategy — Research Audit

**Verdict:** `MULTI_ASSET_TREND_CANDIDATE` (14/14 checks)

Independent research track. No dependency on D+C, 80/20, 60/40 D+C sleeve, or half_protect for parameter choice. Those appear only in an appendix reference table if available.

This audit label is **not** a live-trading endorsement and does not modify IBKR/production configs.

## Pre-registered hypothesis

Absolute momentum vs BIL on eight liquid multi-asset ETFs. Three frozen versions only: `base_12m_equal`, `ensemble_equal`, `ensemble_risk_balanced` (3/6/12 score × inverse-vol budget without renormalizing losers away). No grid search.

## Weight formulas

### base_12m_equal

For each risk ETF \(i\) with fixed budget \(1/8\):

- If \(R_{i,12m} > R_{BIL,12m}\) → weight \(1/8\) in \(i\)
- Else → that \(1/8\) in BIL
- No renormalization across winners

### ensemble_equal

\(\mathrm{score}_i = \#\{h \in \{3,6,12\}: R_{i,h} > R_{BIL,h}\} / 3 \in \{0,1/3,2/3,1\}\)

\(w_i = (1/8)\cdot \mathrm{score}_i\); residual → BIL. Risk sleeve not rescaled to 100%.

### ensemble_risk_balanced (challenger)

1. On the **full** risk pool, `base_i = (1/vol_i) / Σ(1/vol_j)` with 63-day annualized vol.
2. `score_i` identical to ensemble_equal.
3. `w_i = base_i * score_i`.
4. Residual → BIL. **Forbidden:** drop negative-trend names then renormalize survivors to full risk.

## Data audit

- Return basis: `Yahoo_AdjClose_scaled_Open`
- Strict common sample: `2007-05-30` → `2026-08-10` (4830 rows)
- Extreme |Adj Close daily ret| > 25% flags: 0
- Manifest retrieved_at_utc: `2026-08-13T09:36:27.194046+00:00`
- Missing returns are **never** `fillna(0)`.

### Per-symbol coverage

| Symbol | Start | End | Rows | Dup dates | Missing bdys | Inception approx |
|---|---|---|---:|---:|---:|---|
| SPY | 2005-01-03 | 2026-08-10 | 5434 | 0 | 202 | 1993-01-29 |
| EFA | 2005-01-03 | 2026-08-12 | 5436 | 0 | 202 | 2001-08-17 |
| EEM | 2005-01-03 | 2026-08-12 | 5436 | 0 | 202 | 2003-04-11 |
| IEF | 2005-01-03 | 2026-08-10 | 5434 | 0 | 202 | 2002-07-26 |
| TLT | 2005-01-03 | 2026-08-12 | 5436 | 0 | 202 | 2002-07-26 |
| GLD | 2005-01-03 | 2026-08-10 | 5434 | 0 | 202 | 2004-11-18 |
| DBC | 2006-02-06 | 2026-08-12 | 5161 | 0 | 192 | 2006-02-03 |
| VNQ | 2005-01-03 | 2026-08-12 | 5436 | 0 | 202 | 2004-09-29 |
| BIL | 2007-05-30 | 2026-08-10 | 4830 | 0 | 179 | 2007-05-30 |

## Execution

- Month-end close signal → next session open fill
- One-way cost 5bp; weights drift between rebalances
- No shorts, no leverage; idle capital in BIL

## Formal comparison table

| strategy | CAGR | Vol | Sharpe | Sortino | MaxDD | MaxDD days | Calmar | Worst year | Worst 12m | Pos years | Month WR | Ann turn | Trades/yr | Cost drag | Avg BIL | Corr SPY | Beta | Up cap | Down cap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| spy_buy_hold | 11.87% | 19.77% | 0.667 | 0.810 | -50.70% | 674.0 | 0.234 | -34.48% | -31.07% | 84.21% | 67.12% | 0.00% | 0.0 | 0.00% | n/a | 1.000 | 1.000 | 100.00% | 100.00% |
| equal_weight_8_monthly | 5.93% | 12.37% | 0.529 | 0.661 | -36.84% | 664.0 | 0.161 | -23.51% | -22.30% | 73.68% | 60.27% | 17.72% | 12.0 | 0.02% | 0.00% | 0.842 | 0.527 | 51.82% | 52.16% |
| sixty_forty_spy_ief_monthly | 8.57% | 11.15% | 0.795 | 0.989 | -30.88% | 576.0 | 0.278 | -16.94% | -17.80% | 84.21% | 67.12% | 11.47% | 12.0 | 0.01% | 0.00% | 0.970 | 0.547 | 56.61% | 55.13% |
| base_12m_equal | 4.76% | 7.08% | 0.693 | 0.848 | -10.86% | 482.0 | 0.438 | -6.31% | -9.23% | 73.68% | 60.27% | 136.40% | 12.0 | 0.14% | 38.68% | 0.518 | 0.186 | 26.16% | 24.67% |
| ensemble_equal | 4.77% | 6.46% | 0.755 | 0.964 | -9.22% | 629.0 | 0.517 | -4.52% | -8.21% | 78.95% | 62.56% | 162.55% | 12.0 | 0.17% | 39.63% | 0.505 | 0.165 | 25.92% | 24.42% |
| ensemble_risk_balanced | 4.55% | 5.46% | 0.843 | 1.113 | -8.06% | 628.0 | 0.564 | -3.71% | -7.18% | 84.21% | 61.64% | 185.50% | 12.0 | 0.19% | 38.48% | 0.366 | 0.101 | 18.99% | 16.80% |

### Crisis windows (net total return)

| Strategy | 2008 | 2020 | 2022 |
|---|---:|---:|---:|
| spy_buy_hold | -41.85% | -9.18% | -18.18% |
| equal_weight_8_monthly | -30.66% | -6.85% | -13.80% |
| sixty_forty_spy_ief_monthly | -22.99% | -2.23% | -16.57% |
| base_12m_equal | -2.47% | -4.30% | -3.07% |
| ensemble_equal | -3.80% | -2.68% | -2.27% |
| ensemble_risk_balanced | 2.72% | -0.91% | -2.77% |

## Metric C relative wealth

Definition: `relative_nav_t = nav_strategy_t / nav_benchmark_t (both rebased to 1.0 at the first common date). Relative underwater = relative_nav / relative_nav.cummax() - 1.`

| Strategy | vs SPY final | vs SPY rel CAGR | vs SPY max UW | vs SPY UW sess/cal/mo | still UW? | vs 60/40 final | vs 60/40 max UW | still UW? |
|---|---:|---:|---:|---|---|---:|---:|---|
| spy_buy_hold | 1.000 | 0.00% | 0.00% | 0/0/0 | False | 1.735 | -28.68% | False |
| equal_weight_8_monthly | 0.368 | -5.35% | -72.03% | 3762/5466/181 | True | 0.638 | -45.35% | True |
| sixty_forty_spy_ief_monthly | 0.576 | -2.98% | -58.61% | 4382/6362/210 | True | 1.000 | 0.00% | False |
| base_12m_equal | 0.299 | -6.42% | -84.75% | 4382/6362/210 | True | 0.519 | -65.50% | True |
| ensemble_equal | 0.300 | -6.40% | -84.41% | 4382/6362/210 | True | 0.521 | -63.74% | True |
| ensemble_risk_balanced | 0.289 | -6.60% | -85.84% | 4382/6362/210 | True | 0.501 | -65.89% | True |

## Stability (pre-registered only)

| Test | CAGR | Sharpe | MaxDD | Avg BIL |
|---|---:|---:|---:|---:|
| baseline | 4.55% | 0.843 | -8.06% | 38.48% |
| cost_10bp | 4.35% | 0.809 | -8.08% | 38.48% |
| extra_delay | 4.39% | 0.813 | -8.13% | 38.47% |
| exclude_last_1y | 4.05% | 0.759 | -8.06% | 38.85% |
| exclude_last_2y | 3.89% | 0.737 | -8.06% | 38.94% |
| restart_2010 | 4.49% | 0.866 | -8.06% | 38.14% |
| post_2008 | 4.61% | 0.869 | -8.06% | 38.06% |

### Fixed cutoffs (ensemble_risk_balanced)

| Cutoff | CAGR | Sharpe | MaxDD |
|---|---:|---:|---:|
| 2015-12-31 | 3.82% | 0.654 | -7.11% |
| 2018-12-31 | 3.52% | 0.648 | -7.66% |
| 2020-12-31 | 3.98% | 0.733 | -8.06% |
| 2022-12-31 | 3.77% | 0.708 | -8.06% |
| 2024-12-31 | 3.86% | 0.729 | -8.06% |
| latest | 4.55% | 0.843 | -8.06% |

### Leave-one-asset-out (ensemble_risk_balanced)

| Dropped | CAGR | Sharpe | MaxDD |
|---|---:|---:|---:|
| SPY | 3.88% | 0.746 | -7.50% |
| EFA | 4.50% | 0.867 | -7.88% |
| EEM | 4.51% | 0.874 | -7.88% |
| IEF | 5.40% | 0.779 | -11.12% |
| TLT | 4.60% | 0.800 | -9.02% |
| GLD | 4.10% | 0.765 | -8.42% |
| DBC | 4.97% | 0.889 | -9.02% |
| VNQ | 4.51% | 0.858 | -7.25% |

### Asset-group contributions

| Version | Group | CAGR contrib | MaxDD relief |
|---|---|---:|---:|
| ensemble_risk_balanced | equity | 1.03% | 1.04% |
| ensemble_risk_balanced | bonds | -1.02% | 5.35% |
| ensemble_risk_balanced | gold | 0.45% | 0.37% |
| ensemble_risk_balanced | commodities | -0.42% | 0.96% |
| ensemble_risk_balanced | real_estate | 0.03% | -0.81% |
| base_12m_equal | equity | 0.85% | 4.23% |
| base_12m_equal | bonds | -0.36% | 7.25% |
| base_12m_equal | gold | 0.37% | 0.81% |
| base_12m_equal | commodities | -0.43% | 1.54% |
| base_12m_equal | real_estate | -0.07% | -0.08% |
| ensemble_equal | equity | 0.88% | 2.89% |
| ensemble_equal | bonds | -0.54% | 4.48% |
| ensemble_equal | gold | 0.31% | 0.70% |
| ensemble_equal | commodities | -0.35% | 1.30% |
| ensemble_equal | real_estate | 0.00% | -1.04% |

## Gate checklist

- [x] `net_cagr_positive`
- [x] `cagr_clearly_above_bil`
- [x] `sharpe_above_ew`
- [x] `maxdd_shallower_than_ew`
- [x] `not_only_2008_vs_base`
- [x] `exclude_last_1y_not_flip`
- [x] `exclude_last_2y_not_flip`
- [x] `cost_10bp_not_flip`
- [x] `delay_not_flip`
- [x] `fixed_cutoffs_majority`
- [x] `leave_one_out_majority`
- [x] `no_single_etf_dominates_excess`
- [x] `not_cash_mechanical_sharpe`
- [x] `improves_vs_base_risk_adjusted`

## Decision

**MULTI_ASSET_TREND_CANDIDATE** — research shadow only. Not a production/IBKR change, not a claim of prospective live profitability.


## Appendix — prior-strategy references (not used for selection)

| Strategy | CAGR | Sharpe | MaxDD |
|---|---:|---:|---:|
| appendix_80_20_spy_dc | 11.53% | 0.726 | -42.33% |
| appendix_60_40_spy_dc | 11.09% | 0.782 | -32.79% |
| appendix_dc_only | 9.29% | 0.750 | -17.97% |

## Reproduce

```bash
cd /home/ec2-user/strategy-backtest/multi_asset_etf_trend
python3 -m pip install -e '.[dev]'
multi-asset-etf-trend fetch
multi-asset-etf-trend audit-data
multi-asset-etf-trend full-audit
pytest -q
```

Run directory: `/home/ec2-user/strategy-backtest/multi_asset_etf_trend/reports/runs/20260813T094733Z_full-audit_384c1d9186e2`
