# v2 Frozen Final Research Report

## Frozen candidates

| Key | Label | ID | Evidence tier |
|---|---|---|---|
| A | QQQ/SHY | BTC_QQQ_SHY | REFERENCE_CORE |
| B | QQQ/BIL | BTC_QQQ_BIL | POST_TEST_CANDIDATE |
| C | SMH/SHY | BTC_SMH_SHY | TRAIN_PRE_REGISTERED |
| | OFF pick: `SHY` train Sharpe {'SHY': 0.8407263916712023, 'BIL': 0.8306919737508083} | | |
| D | SPY/BIL | BTC_SPY_BIL | TRAIN_AND_WF_EXPLORATORY |

## 1. Anchored walk-forward (with audited costs)

Pass = Sharpe>1 AND cum active>0 vs train-calibrated vol-matched static.

### Block `wf_2019_2020` test 2019-01-01→2020-12-31

| Candidate | CAGR | Sharpe | MaxDD | Cum active | Edge Sharpe | Pass |
|---|---:|---:|---:|---:|---:|---|
| QQQ/SHY | 28.07% | 1.800 | -13.6% | 8.8% | 0.352 | PASS |
| QQQ/BIL | 28.04% | 1.800 | -13.5% | 10.1% | 0.406 | PASS |
| SMH/SHY | 31.99% | 1.489 | -13.9% | -1.6% | 0.061 | — |
| SPY/BIL | 13.62% | 1.118 | -12.9% | -4.7% | -0.024 | — |

### Block `wf_2021_2022` test 2021-01-01→2022-12-31

| Candidate | CAGR | Sharpe | MaxDD | Cum active | Edge Sharpe | Pass |
|---|---:|---:|---:|---:|---:|---|
| QQQ/SHY | 8.23% | 0.583 | -12.7% | 14.8% | 0.588 | — |
| QQQ/BIL | 10.62% | 0.748 | -11.9% | 18.6% | 0.717 | — |
| SMH/SHY | 19.17% | 0.923 | -19.0% | 22.4% | 0.603 | — |
| SPY/BIL | 10.13% | 0.994 | -6.9% | 7.9% | 0.530 | — |

### Block `wf_2023_2024` test 2023-01-01→2024-12-31

| Candidate | CAGR | Sharpe | MaxDD | Cum active | Edge Sharpe | Pass |
|---|---:|---:|---:|---:|---:|---|
| QQQ/SHY | 19.46% | 1.465 | -9.5% | 2.8% | -0.213 | PASS |
| QQQ/BIL | 18.96% | 1.441 | -9.3% | 2.3% | -0.228 | PASS |
| SMH/SHY | 23.23% | 1.089 | -19.5% | 0.2% | -0.091 | PASS |
| SPY/BIL | 13.29% | 1.435 | -6.4% | 1.7% | -0.319 | PASS |

### Block `wf_2025_2026` test 2025-01-01→2026-08-06

| Candidate | CAGR | Sharpe | MaxDD | Cum active | Edge Sharpe | Pass |
|---|---:|---:|---:|---:|---:|---|
| QQQ/SHY | 19.60% | 1.821 | -7.7% | 21.6% | 1.415 | PASS |
| QQQ/BIL | 18.92% | 1.775 | -7.7% | 20.3% | 1.360 | PASS |
| SMH/SHY | 39.05% | 1.770 | -14.8% | 20.4% | 0.910 | PASS |
| SPY/BIL | 11.75% | 1.547 | -5.2% | 9.0% | 0.964 | PASS |

## 2. Cross-sectional regime diagnostics (ON/SHY, with costs)

Judgment: **`MIXED_GROWTH_TILT_WITH_REGIME_DEPENDENCE`**

### Ranks — `wf_2019_2020` (1=best Sharpe)
| Rank | ON | Sharpe | Cum active | MaxDD | Bucket |
|---|---:|---:|---:|---:|---|
| 1 | QQQ | 1.800 | 8.8% | -13.6% | growth |
| 2 | SOXX | 1.540 | -2.0% | -14.7% | growth |
| 3 | SMH | 1.489 | -1.6% | -13.9% | growth |
| 4 | IWO | 1.297 | 6.5% | -11.3% | growth |
| 5 | SPY | 1.118 | -6.3% | -12.9% | broad |
| 6 | IWM | 0.845 | -1.1% | -12.1% | small |
_mean growth rank=2.5, SPY rank=5, SMH rank=3, QQQ rank=1_

### Ranks — `wf_2021_2022` (1=best Sharpe)
| Rank | ON | Sharpe | Cum active | MaxDD | Bucket |
|---|---:|---:|---:|---:|---|
| 1 | SMH | 0.923 | 22.4% | -19.0% | growth |
| 2 | SOXX | 0.881 | 19.9% | -19.7% | growth |
| 3 | SPY | 0.750 | 4.3% | -8.4% | broad |
| 4 | QQQ | 0.583 | 14.8% | -12.7% | growth |
| 5 | IWM | 0.291 | -0.1% | -12.7% | small |
| 6 | IWO | 0.130 | 0.8% | -17.0% | growth |
_mean growth rank=3.2, SPY rank=3, SMH rank=1, QQQ rank=4_

### Ranks — `wf_2023_2024` (1=best Sharpe)
| Rank | ON | Sharpe | Cum active | MaxDD | Bucket |
|---|---:|---:|---:|---:|---|
| 1 | QQQ | 1.465 | 2.8% | -9.5% | growth |
| 2 | SPY | 1.463 | 2.2% | -6.0% | broad |
| 3 | SMH | 1.089 | 0.2% | -19.5% | growth |
| 4 | SOXX | 0.731 | -0.1% | -22.5% | growth |
| 5 | IWO | 0.542 | -1.2% | -17.3% | growth |
| 6 | IWM | 0.353 | -7.6% | -18.8% | small |
_mean growth rank=3.2, SPY rank=2, SMH rank=3, QQQ rank=1_

### Ranks — `wf_2025_2026` (1=best Sharpe)
| Rank | ON | Sharpe | Cum active | MaxDD | Bucket |
|---|---:|---:|---:|---:|---|
| 1 | QQQ | 1.821 | 21.6% | -7.7% | growth |
| 2 | SMH | 1.770 | 20.4% | -14.8% | growth |
| 3 | SOXX | 1.657 | 24.4% | -17.2% | growth |
| 4 | SPY | 1.606 | 10.1% | -4.7% | broad |
| 5 | IWO | 0.965 | 11.5% | -6.1% | growth |
| 6 | IWM | 0.752 | 0.9% | -7.2% | small |
_mean growth rank=2.8, SPY rank=4, SMH rank=2, QQQ rank=1_

## 3. Cost-adjusted risk-matched (train w frozen → test)

Costs: 5bps one-way + half-spreads

| Candidate | Tier | Train Sharpe | Test Sharpe | Test MaxDD | Test cum active | RT bps |
|---|---|---:|---:|---:|---:|---:|
| QQQ/SHY | REFERENCE_CORE | 1.117 | 1.195 | -12.7% | 42.5% | 13.0 |
| QQQ/BIL | POST_TEST_CANDIDATE | 1.109 | 1.241 | -11.9% | 44.9% | 13.0 |
| SMH/SHY | TRAIN_PRE_REGISTERED | 0.861 | 1.215 | -19.5% | 46.0% | 13.5 |
| SPY/BIL | TRAIN_AND_WF_EXPLORATORY | 0.882 | 1.289 | -6.9% | 19.0% | 13.0 |

## Verdict labels (multi-conclusion allowed)

- Defensive/Core: `BTC_QQQ_SHY_CORE_CANDIDATE`
- Broad equity: `SPY_BIL_PASS_2_4_NOT_BROAD`
- Aggressive: `SMH/SHY_PASS_2_4_NOT_AGGRESSIVE`
- BIL parking: `BIL_INTERESTING_BUT_NOT_VALIDATED`
- Cross-section: `MIXED_GROWTH_TILT_WITH_REGIME_DEPENDENCE`

Pass blocks (with costs): `{"QQQ/SHY": {"with_costs": 3, "adj_0bps": 3}, "QQQ/BIL": {"with_costs": 3, "adj_0bps": 3}, "SMH/SHY": {"with_costs": 2, "adj_0bps": 2}, "SPY/BIL": {"with_costs": 2, "adj_0bps": 3}}`

Multi-label allowed: do not pick single champion; map candidates to roles by WF stability with costs.
