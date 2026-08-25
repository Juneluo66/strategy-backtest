# Low-MAX Defensive Research

## Scope

Parent project `max_effect_vix` conclusion remains frozen: **REJECTED_AS_INDEPENDENT_ALPHA**.

This branch does **not** re-test the MAX anomaly / short high-MAX alpha claim.
Questions: long-only defensive usefulness, high-MAX as exclusion filter, and whether MAX is merely a low-vol/beta proxy.

### Frozen definition (from parent PURCHASE_GATE / config_snapshot)

- MAX5, lookback 21
- Low-MAX: decile 0.1, cap 25
- Costs: 5.0 bp one-way; next-open execution; monthly rebalance
- Eval window: 2015-03-02 → 2026-08-07

### Data status

- `DATA_TIER`: `HISTORICAL_SP500_APPROX`
- `SURVIVORSHIP_BIAS`: `REDUCED_NOT_ELIMINATED`
- `PIT_VALIDATED`: `False`
- `DELISTING_RETURN`: `UNAVAILABLE`
- `SIZE_NEUTRAL`: `BLOCKED_BY_PIT_MARKET_CAP`
- `SIZE_VALUATION_QUALITY`: `BLOCKED_BY_PIT_DATA`

No paid data purchased. Style ETFs only if free Yahoo bars exist (no inception backfill).

- SPLV (low_volatility): compared from 2015-03-02 to 2026-08-07
- SPYV (value): compared from 2015-03-02 to 2026-08-07
- IWD (value_alt): compared from 2015-03-02 to 2026-08-07

## Phase 1 — Benchmark comparison

| Label | Net CAGR | Vol | Sharpe | Sortino | MaxDD | Calmar | β | Down β | Worst month | Ann. TO | Cost drag |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SPY_BH | 0.1390 | 0.177 | 0.826 | 1.008 | -0.337 | 0.412 | 1.000 | 1.000 | -0.125 | 0.000 | 0.0000 |
| EW_HIST_SP500 | 0.1180 | 0.180 | 0.711 | 0.862 | -0.393 | 0.300 | 0.961 | 1.001 | -0.177 | 0.087 | 0.0001 |
| LOW_MAX | 0.0832 | 0.152 | 0.603 | 0.755 | -0.331 | 0.251 | 0.673 | 0.749 | -0.098 | 9.972 | 0.0109 |
| SPLV_low_volatility | 0.0851 | 0.153 | 0.612 | 0.726 | -0.363 | 0.235 | 0.676 | 0.764 | -0.131 | 0.000 | 0.0000 |
| SPYV_value | 0.1083 | 0.167 | 0.700 | 0.859 | -0.369 | 0.294 | 0.876 | 0.908 | -0.153 | 0.000 | 0.0000 |
| IWD_value_alt | 0.1052 | 0.171 | 0.672 | 0.818 | -0.385 | 0.273 | 0.898 | 0.940 | -0.174 | 0.000 | 0.0000 |

### Low-MAX vs SPY relative

- Excess CAGR: -0.0591
- Tracking error: 0.111
- Information ratio: -0.495
- Upside capture: 0.599
- Downside capture: 0.594

### Value checklist vs SPY

- `A_higher_return`: **False**
- `B_higher_sharpe`: **False**
- `C_lower_drawdown`: **True**
- `D_lower_beta`: **True**
- `E_better_downside_protection`: **True**
- `F_nothing`: **False**

## Phase 2 — High-MAX exclusion grid (pre-specified 10/20/30)

Flag: **NO_SYSTEMATIC_IMPROVEMENT**

| Label | Net CAGR | Sharpe | Sortino | MaxDD | Vol | β | Down β | Ann. TO | ΔCAGR | ΔSharpe | ΔMaxDD | ΔVol | ΔTO |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EW_baseline | 0.1180 | 0.711 | 0.862 | -0.393 | 0.180 | 0.961 | 1.001 | 0.087 | NA | NA | NA | NA | NA |
| EXCLUDE_HIGH_MAX_10 | 0.1063 | 0.671 | 0.806 | -0.391 | 0.173 | 0.918 | 0.969 | 0.881 | -0.0117 | -0.040 | 0.001 | -0.007 | 0.795 |
| EXCLUDE_HIGH_MAX_20 | 0.1012 | 0.657 | 0.790 | -0.387 | 0.168 | 0.885 | 0.940 | 1.644 | -0.0168 | -0.053 | 0.006 | -0.011 | 1.557 |
| EXCLUDE_HIGH_MAX_30 | 0.0976 | 0.649 | 0.779 | -0.381 | 0.165 | 0.857 | 0.916 | 2.419 | -0.0203 | -0.062 | 0.012 | -0.015 | 2.332 |

## Phase 3 — Low-MAX anatomy

Size / valuation / quality / sector: **BLOCKED_BY_PIT_DATA** (not fabricated).

| Trait | Mean diff (Low-MAX − universe) | Median diff | Pct months Low-MAX lower |
|---|---:|---:|---:|
| realized_vol_20d | -0.1093 | -0.0990 | 1.000 |
| realized_vol_60d | -0.0854 | -0.0754 | 0.993 |
| realized_vol_252d | -0.0726 | -0.0715 | 0.964 |
| beta_60d | -0.3878 | -0.4113 | 1.000 |
| beta_252d | -0.3192 | -0.3249 | 0.957 |
| mom_12_1 | -0.0065 | -0.0054 | 0.471 |
| downside_vol_60d | -0.0443 | -0.0389 | 1.000 |
| recent_drawdown_252d | 0.0251 | 0.0149 | 0.261 |
| max_factor | -0.0115 | -0.0106 | 1.000 |

FF3 loadings from parent gate remain indirect evidence only (not stock-level PIT exposures).

## Phase 4 — Residual / incremental value

Flag: **NO_CLEAR_INCREMENT_AFTER_VOL_CONTROL**

| Control | Variant | Δ/level CAGR | Sharpe | MaxDD |
|---|---|---:|---:|---:|
| vol | all_within_buckets | 0.1175 | 0.713 | -0.393 |
| vol | exclude_high_max_20_within_buckets | 0.1060 | 0.660 | -0.401 |
| vol | incremental_exclude_minus_all | -0.0115 | -0.053 | -0.008 |
| beta | all_within_buckets | 0.1175 | 0.713 | -0.393 |
| beta | exclude_high_max_20_within_buckets | 0.1064 | 0.667 | -0.392 |
| beta | incremental_exclude_minus_all | -0.0111 | -0.047 | 0.000 |

## Phase 5 — Regime stability

Flag: **CROSS_REGIME_POSITIVE**

| Regime | Strategy | Net CAGR | Sharpe | MaxDD | β | Ann. TO |
|---|---|---:|---:|---:|---:|---:|
| P1_2015_2018 | EW_baseline | 0.0594 | 0.507 | -0.186 | 0.923 | 0.182 |
| P1_2015_2018 | LOW_MAX | 0.0711 | 0.644 | -0.170 | 0.735 | 10.107 |
| P1_2015_2018 | EXCLUDE_HIGH_MAX_20 | 0.0616 | 0.546 | -0.174 | 0.867 | 1.855 |
| P2_2019_2022 | EW_baseline | 0.1390 | 0.664 | -0.393 | 1.020 | 0.038 |
| P2_2019_2022 | LOW_MAX | 0.1392 | 0.774 | -0.331 | 0.717 | 9.743 |
| P2_2019_2022 | EXCLUDE_HIGH_MAX_20 | 0.1270 | 0.647 | -0.387 | 0.954 | 1.543 |
| P3_2023_2026 | EW_baseline | 0.1571 | 1.104 | -0.178 | 0.816 | 0.040 |
| P3_2023_2026 | LOW_MAX | 0.0333 | 0.318 | -0.188 | 0.482 | 10.343 |
| P3_2023_2026 | EXCLUDE_HIGH_MAX_20 | 0.1130 | 0.879 | -0.164 | 0.697 | 1.574 |

## Phase 6 — Crisis / downside (auto-detected SPY stress windows)

| Window | Type | Strategy | Crisis return | MaxDD | Downside capture | Recovery days |
|---|---|---|---:|---:|---:|---:|
| DD_2018-09-20_2019-04-12 | drawdown | SPY | 0.0111 | -0.193 | 1.000 | 101 |
| DD_2018-09-20_2019-04-12 | drawdown | EW | 0.0224 | -0.186 | 0.913 | 98 |
| DD_2018-09-20_2019-04-12 | drawdown | LOW_MAX | -0.0024 | -0.170 | 0.644 | NA |
| DD_2018-09-20_2019-04-12 | drawdown | EXCLUDE_20 | 0.0221 | -0.174 | 0.825 | 98 |
| DD_2020-02-19_2020-08-07 | drawdown | SPY | 0.0038 | -0.337 | 1.000 | 136 |
| DD_2020-02-19_2020-08-07 | drawdown | EW | -0.0637 | -0.393 | 1.184 | NA |
| DD_2020-02-19_2020-08-07 | drawdown | LOW_MAX | 0.0068 | -0.329 | 0.797 | 134 |
| DD_2020-02-19_2020-08-07 | drawdown | EXCLUDE_20 | -0.0783 | -0.386 | 1.108 | NA |
| DD_2022-01-03_2023-12-13 | drawdown | SPY | 0.0179 | -0.245 | 1.000 | 426 |
| DD_2022-01-03_2023-12-13 | drawdown | EW | 0.0143 | -0.208 | 0.920 | 439 |
| DD_2022-01-03_2023-12-13 | drawdown | LOW_MAX | -0.0270 | -0.155 | 0.549 | 159 |
| DD_2022-01-03_2023-12-13 | drawdown | EXCLUDE_20 | -0.0055 | -0.193 | 0.839 | NA |
| DD_2025-02-19_2025-06-26 | drawdown | SPY | 0.0066 | -0.188 | 1.000 | 79 |
| DD_2025-02-19_2025-06-26 | drawdown | EW | 0.0017 | -0.161 | 0.848 | 77 |
| DD_2025-02-19_2025-06-26 | drawdown | LOW_MAX | -0.1372 | -0.176 | 0.763 | NA |
| DD_2025-02-19_2025-06-26 | drawdown | EXCLUDE_20 | -0.0165 | -0.144 | 0.760 | NA |
| HIVOL_2015-08-26_2015-09-24 | high_vol | SPY | 0.0354 | -0.038 | 1.000 | 0 |
| HIVOL_2015-08-26_2015-09-24 | high_vol | EW | 0.0267 | -0.037 | 1.024 | 0 |
| HIVOL_2015-08-26_2015-09-24 | high_vol | LOW_MAX | 0.0468 | -0.034 | 0.772 | 0 |
| HIVOL_2015-08-26_2015-09-24 | high_vol | EXCLUDE_20 | 0.0297 | -0.036 | 0.964 | 0 |
| HIVOL_2018-02-09_2018-03-06 | high_vol | SPY | 0.0592 | -0.037 | 1.000 | 0 |
| HIVOL_2018-02-09_2018-03-06 | high_vol | EW | 0.0530 | -0.034 | 0.961 | 0 |
| HIVOL_2018-02-09_2018-03-06 | high_vol | LOW_MAX | 0.0408 | -0.038 | 1.177 | 0 |
| HIVOL_2018-02-09_2018-03-06 | high_vol | EXCLUDE_20 | 0.0482 | -0.035 | 1.012 | 0 |
| HIVOL_2018-12-26_2019-01-24 | high_vol | SPY | 0.1246 | -0.024 | 1.000 | 0 |
| HIVOL_2018-12-26_2019-01-24 | high_vol | EW | 0.1267 | -0.022 | 0.904 | 0 |
| HIVOL_2018-12-26_2019-01-24 | high_vol | LOW_MAX | 0.1028 | -0.011 | 0.253 | 0 |
| HIVOL_2018-12-26_2019-01-24 | high_vol | EXCLUDE_20 | 0.1175 | -0.021 | 0.760 | 0 |
| HIVOL_2020-02-27_2020-05-20 | high_vol | SPY | -0.0412 | -0.283 | 1.000 | NA |
| HIVOL_2020-02-27_2020-05-20 | high_vol | EW | -0.1046 | -0.340 | 1.186 | NA |
| HIVOL_2020-02-27_2020-05-20 | high_vol | LOW_MAX | -0.0306 | -0.301 | 0.882 | NA |
| HIVOL_2020-02-27_2020-05-20 | high_vol | EXCLUDE_20 | -0.1181 | -0.337 | 1.150 | NA |
| HIVOL_2020-06-11_2020-07-10 | high_vol | SPY | -0.0000 | -0.038 | 1.000 | NA |
| HIVOL_2020-06-11_2020-07-10 | high_vol | EW | -0.0407 | -0.058 | 1.274 | NA |
| HIVOL_2020-06-11_2020-07-10 | high_vol | LOW_MAX | 0.0068 | -0.025 | 0.537 | 11 |
| HIVOL_2020-06-11_2020-07-10 | high_vol | EXCLUDE_20 | -0.0263 | -0.044 | 1.014 | NA |
| HIVOL_2022-04-29_2022-07-13 | high_vol | SPY | -0.1107 | -0.145 | 1.000 | NA |
| HIVOL_2022-04-29_2022-07-13 | high_vol | EW | -0.1124 | -0.145 | 0.925 | NA |
| HIVOL_2022-04-29_2022-07-13 | high_vol | LOW_MAX | -0.0454 | -0.114 | 0.550 | NA |
| HIVOL_2022-04-29_2022-07-13 | high_vol | EXCLUDE_20 | -0.0969 | -0.133 | 0.812 | NA |
| HIVOL_2022-10-13_2022-12-09 | high_vol | SPY | 0.1030 | -0.046 | 1.000 | 0 |
| HIVOL_2022-10-13_2022-12-09 | high_vol | EW | 0.1335 | -0.033 | 0.824 | 0 |
| HIVOL_2022-10-13_2022-12-09 | high_vol | LOW_MAX | 0.1362 | -0.028 | 0.331 | 0 |
| HIVOL_2022-10-13_2022-12-09 | high_vol | EXCLUDE_20 | 0.1339 | -0.032 | 0.760 | 0 |
| HIVOL_2025-04-03_2025-05-09 | high_vol | SPY | -0.0003 | -0.075 | 1.000 | 24 |
| HIVOL_2025-04-03_2025-05-09 | high_vol | EW | -0.0087 | -0.080 | 0.923 | NA |
| HIVOL_2025-04-03_2025-05-09 | high_vol | LOW_MAX | -0.0521 | -0.092 | 0.815 | NA |
| HIVOL_2025-04-03_2025-05-09 | high_vol | EXCLUDE_20 | -0.0210 | -0.081 | 0.873 | NA |

## Phase 7 — Decision gate

### Classification: **REJECT**

Rationale:

- LOW_MAX vs SPY: sharpe 0.603 vs 0.826; cagr 0.083 vs 0.139; maxDD -0.331 vs -0.337; beta 0.673.
- LOW_MAX vs EW: sharpe 0.603 vs 0.711; maxDD -0.331 vs -0.393.
- Exclusion grid flag: NO_SYSTEMATIC_IMPROVEMENT.
- Residual after vol control: NO_CLEAR_INCREMENT_AFTER_VOL_CONTROL.
- Regime flag: CROSS_REGIME_POSITIVE.
- Fraction of auto stress windows with LOW_MAX > SPY return: 0.50.
- Anatomy: mean 60d vol diff (Low-MAX - universe) = -0.0854.
- No clear outperformance vs SPY/EW and exclusion grid is weak or parameter-sensitive.

### Multi-factor follow-on

Allowed only if classification is `USEFUL_AS_RISK_FILTER`, `PROMISING_LONG_ONLY_SIGNAL`, or `NEEDS_PAID_PIT_VALIDATION` (which presupposes B/C-class free evidence). Otherwise **stop researching MAX** — do not launch `low_lottery_quality_value_momentum`.
