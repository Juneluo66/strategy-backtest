# Multi-Asset ETF Trend — Return Adequacy Audit

**Verdict:** `CAPITAL_PRESERVATION_CANDIDATE`

Frozen rules unchanged (universe, 3/6/12 signals, 63d vol, weights, monthly cadence, 5bp next-open). This audit only asks whether `ensemble_risk_balanced` earns enough *incremental* return beyond long BIL, or is mainly a cash sleeve with a Sharpe coat of paint.

Inflation / real purchasing power: **NOT_COMPUTED** (no reliable PIT inflation series in this track; will not backfill with latest CPI).

## 1. Full sample

| Strategy | CAGR | vs BIL | Sharpe(rf=BIL) | Sortino | MaxDD | Calmar | Final W | Avg risk | Eq | Bond | Gold | Cmdty | RE | BIL |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bil_buy_hold | 1.27% | 0.00% | 0.000 | 2.307 | -0.78% | 1.627 | 1.258 | 0.00% | n/a | n/a | n/a | n/a | n/a | 100.00% |
| ensemble_risk_balanced | 4.55% | 3.28% | 0.611 | 1.113 | -8.06% | 0.564 | 2.245 | 61.52% | 20.88% | 22.68% | 6.97% | 4.62% | 6.38% | 38.48% |
| ensemble_equal | 4.77% | 3.50% | 0.559 | 0.964 | -9.22% | 0.517 | 2.333 | 60.37% | 24.70% | 13.67% | 7.83% | 6.02% | 8.15% | 39.63% |
| sixty_forty_spy_ief_monthly | 8.57% | 7.30% | 0.682 | 0.989 | -30.88% | 0.278 | 4.464 | 100.00% | 60.10% | 39.90% | n/a | n/a | n/a | 0.00% |
| spy_buy_hold | 11.87% | 10.60% | 0.603 | 0.810 | -50.70% | 0.234 | 7.695 | 100.00% | 100.00% | n/a | n/a | n/a | n/a | 0.00% |

Sample: `2008-06-02` → `2026-08-10`

## 2. Periods

| Period | Strategy | Strat CAGR | BIL CAGR | Strat−BIL | 60/40 CAGR | MaxDD | Sharpe(rf=BIL) | Avg BIL |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2008-2012 | bil_buy_hold | 0.20% | 0.20% | 0.00% | 5.36% | -0.77% | 0.000 | 100.00% |
| 2008-2012 | ensemble_risk_balanced | 5.98% | 0.20% | 5.78% | 5.36% | -7.11% | 0.850 | 29.90% |
| 2008-2012 | ensemble_equal | 5.02% | 0.20% | 4.82% | 5.36% | -7.73% | 0.611 | 34.93% |
| 2008-2012 | sixty_forty_spy_ief_monthly | 5.36% | 0.20% | 5.17% | 5.36% | -30.88% | 0.424 | 0.00% |
| 2008-2012 | spy_buy_hold | 2.62% | 0.20% | 2.42% | 5.36% | -50.70% | 0.222 | 0.00% |
| 2013-2017 | bil_buy_hold | 0.10% | 0.10% | 0.00% | 10.00% | -0.33% | 0.000 | 100.00% |
| 2013-2017 | ensemble_risk_balanced | 2.48% | 0.10% | 2.38% | 10.00% | -7.66% | 0.564 | 36.27% |
| 2013-2017 | ensemble_equal | 2.56% | 0.10% | 2.46% | 10.00% | -8.59% | 0.533 | 38.91% |
| 2013-2017 | sixty_forty_spy_ief_monthly | 10.00% | 0.10% | 9.90% | 10.00% | -6.84% | 1.443 | 0.00% |
| 2013-2017 | spy_buy_hold | 15.72% | 0.10% | 15.62% | 10.00% | -13.02% | 1.280 | 0.00% |
| 2018-2022 | bil_buy_hold | 1.09% | 1.09% | 0.00% | 5.92% | -0.21% | 0.000 | 100.00% |
| 2018-2022 | ensemble_risk_balanced | 3.07% | 1.09% | 1.98% | 5.92% | -8.06% | 0.419 | 46.17% |
| 2018-2022 | ensemble_equal | 3.52% | 1.09% | 2.43% | 5.92% | -9.22% | 0.434 | 45.12% |
| 2018-2022 | sixty_forty_spy_ief_monthly | 5.92% | 1.09% | 4.83% | 5.92% | -21.21% | 0.436 | 0.00% |
| 2018-2022 | spy_buy_hold | 9.33% | 1.09% | 8.24% | 5.92% | -33.72% | 0.472 | 0.00% |
| 2023-latest | bil_buy_hold | 4.57% | 4.57% | 0.00% | 14.71% | -0.02% | 0.000 | 100.00% |
| 2023-latest | ensemble_risk_balanced | 7.77% | 4.57% | 3.20% | 14.71% | -5.21% | 0.572 | 41.80% |
| 2023-latest | ensemble_equal | 9.42% | 4.57% | 4.85% | 14.71% | -5.66% | 0.709 | 38.99% |
| 2023-latest | sixty_forty_spy_ief_monthly | 14.71% | 4.57% | 10.14% | 14.71% | -10.55% | 1.020 | 0.00% |
| 2023-latest | spy_buy_hold | 23.11% | 4.57% | 18.54% | 14.71% | -18.76% | 1.161 | 0.00% |

## 3. Relative sufficiency

- Strategy final wealth / BIL final wealth: **1.785**
- Metric C vs BIL final relative NAV: **1.787**
- Metric C vs BIL max relative UW: -8.90%; still underwater: True
- Definition: `relative_nav_t = nav_strategy_t / nav_benchmark_t (both rebased to 1.0 at the first common date). Relative underwater = relative_nav / relative_nav.cummax() - 1.`
- Rolling 3y beat BIL: 92.86% (n=182)
- Rolling 5y beat BIL: 100.00% (n=158)
- Rolling 3y beat 60/40: 2.75% (n=182)
- Rolling 5y beat 60/40: 0.00% (n=158)
- Annualized excess over BIL (geometric CAGR gap): 3.28%
- CAGR per +1pp MaxDD vs BIL (excess / ΔMaxDD × 1pp): 0.450%
- Real purchasing power vs inflation: **NOT_COMPUTED**

## 4. Return sources (not labeling BIL interest as trend alpha)

| Component | CAGR |
|---|---:|
| BIL base | 1.27% |
| Passive EW8 (always on) | 5.93% |
| Passive risk premium vs BIL | 4.66% |
| Timing vs passive EW8 (`ensemble_equal − EW8`) | -1.16% |
| Risk-balance vs `ensemble_equal` (gross) | -0.03% |
| Cost drag | 0.19% |
| Net `ensemble_risk_balanced` | 4.55% |
| Check: net − BIL | 3.28% |

Arithmetic annualized group contributions (end-weight × close-to-close approx):

| Piece | Ann. contrib |
|---|---:|
| BIL weight × BIL return | 0.56% |
| equity weight × asset return | 2.47% |
| bonds weight × asset return | 1.19% |
| gold weight × asset return | 1.01% |
| commodities weight × asset return | 0.26% |
| real_estate weight × asset return | 0.64% |
| Cost drag | -0.19% |
| Sum risk excess over BIL | 4.86% |
| Reconciliation ann. error (engine vs CC approx) | -1.33% |

- BIL基础收益 = telescoping bil_base (and bil_weight_times_bil_return).
- 各风险ETF被动收益贡献 ≈ passive_equal_weight_8 − bil_base (满仓等权溢价).
- 趋势择时贡献 = ensemble_equal − passive_equal_weight_8 (通常为负的CAGR、换取回撤).
- 风险平衡贡献 = erb_gross − ensemble_equal.
- 交易成本拖累 = erb_gross − erb_net.
- 持有BIL的利息不是趋势alpha；alpha仅存在于相对BIL/被动的增量项。

## Gate checklist

- [x] `beats_bil_cagr_1pp`
- [x] `wealth_vs_bil_gt_1_2`
- [x] `metric_c_bil_final_gt_1`
- [x] `rolling_beat_bil_3y_ge_60`
- [x] `rolling_beat_bil_5y_ge_60`
- [x] `maxdd_much_better_than_60_40`
- [x] `lags_60_40_wealth`
- [x] `rolling_beat_60_40_3y_lt_40`
- [x] `rolling_beat_60_40_5y_lt_40`
- [x] `incremental_vs_bil_not_tiny`
- [x] `not_only_bil_carry`

## Decision

**A. CAPITAL_PRESERVATION_CANDIDATE** — Beats BIL with shallow drawdowns and stable risk-adjusted stats, but long-run wealth and rolling windows remain clearly behind 60/40. Useful as a preservation / ballast research sleeve, not as a return engine.

No IBKR changes. No frozen-rule edits. No further parameter search.

## Reproduce

```bash
cd /home/ec2-user/strategy-backtest/multi_asset_etf_trend
python3 -m pip install -e '.[dev]'
multi-asset-etf-trend return-adequacy-audit
pytest -q
```

Run directory: `reports/runs/20260813T102622Z_return-adequacy-audit_384c1d9186e2`
