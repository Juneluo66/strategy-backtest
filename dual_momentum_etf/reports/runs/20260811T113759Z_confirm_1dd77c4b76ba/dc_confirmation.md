# D+C Confirmation Validation

- Frozen variant: `attribution_DC` (category + trend consistency, **no vol-adj**, no hysteresis, no B)
- Common start: `2005-02-01`
- Verdict: **PASS**

## Gates

- `cagr_only_mildly_lags_A`: PASS
- `majority_windows_lower_dd`: PASS
- `oos_not_clearly_broken`: PASS
- `not_only_2008`: PASS
- `cost_stable`: PASS
- `neighborhood_stable`: PASS
- `pit_ok`: PASS
- notes: `{"cagr_gap_dc_minus_a": -0.001644705433471394, "dd_better_pct": 0.8288288288288288, "sharpe_better_pct": 0.6306306306306306, "mean_cagr_gap_roll": -0.0023636618975590336}`

## Full sample

| Strategy | CAGR | Sharpe | MaxDD | Worst12M |
|---|---:|---:|---:|---:|
| D+C | 9.53% | 0.75 | -17.97% | -10.91% |
| A | 9.69% | 0.72 | -22.67% | -20.95% |
| 60/40 | 8.43% | 0.80 | -31.53% | -27.47% |
| simple_dual | 9.42% | 0.69 | -22.81% | -20.95% |
| SPY | 11.12% | 0.65 | -55.19% | -47.35% |

## Locked OOS `2024-01-01` → `2026-06-30`

| Strategy | CAGR | Sharpe | MaxDD | Total return |
|---|---:|---:|---:|---:|
| D+C | 25.85% | 1.52 | -13.94% | 76.86% |
| A | 28.79% | 1.63 | -13.94% | 87.30% |
| 60/40 | 14.11% | 1.37 | -10.53% | 38.74% |
| simple_dual | 29.92% | 1.65 | -13.94% | 91.40% |
| SPY | 21.43% | 1.30 | -18.76% | n/a |

## Rolling 3Y (D+C vs A)

- Windows: 222
- Mean CAGR gap (DC−A): -0.24%
- Median CAGR gap: -0.13%
- Share windows DC CAGR > A: 47.75%
- Share windows DC MaxDD better: 82.88%
- Share windows DC Sharpe better: 63.06%

## Crisis dependence (exclude GFC returns)

- GFC total return DC/A: 9.05% / -9.36%
- Ex-2008 CAGR gap DC−A: -1.11%
- Ex-2008 rolling DD-better%: 67.57%

## Cost sensitivity (one-way bps)

| bps | DC CAGR | DC Sharpe | A CAGR | CAGR gap |
|---:|---:|---:|---:|---:|
| 5 | 9.53% | 0.75 | 9.69% | -0.16% |
| 10 | 9.14% | 0.72 | 9.38% | -0.24% |
| 20 | 8.38% | 0.67 | 8.77% | -0.39% |
- Cost stability flag: **PASS**

## C-horizon neighborhood (diagnostic only; do not re-pick)

- Frozen horizons: `3/6/12`
- Neighborhood is diagnostic only; frozen 3/6/12 is NOT reselected by Sharpe.

| Horizons | Frozen? | CAGR | Sharpe | MaxDD |
|---|---|---:|---:|---:|
| 3/6/12 | yes | 9.53% | 0.75 | -17.97% |
| 2/6/12 | no | 8.12% | 0.68 | -18.98% |
| 3/5/12 | no | 9.64% | 0.75 | -17.97% |
| 3/6/11 | no | 10.06% | 0.78 | -17.97% |
| 4/6/12 | no | 10.06% | 0.77 | -19.21% |
- Neighborhood stability flag: **PASS**

## PIT / inception audit

- Overall: **PASS**
- SGOV inception: `2020-06-01`
- `all_signal_dates_are_month_ends`: ok
- `all_execution_after_signal`: ok
- `no_pre_inception_risk_weights`: ok
- `cash_proxy_before_sgov`: ok
- `month_end_returns_reproducible`: ok

## Holdings / concentration

- Avg weight QQQ/SPY/cash: 19.11% / 3.09% / 25.68%
- Max single risk weight: 50.00%
- QQQ held months: 38.22%; cash-only months: 13.51%
- Category avg weights: `{"cash": 0.25675675675675674, "defensive": 0.2277992277992278, "intl": 0.20656370656370657, "us": 0.3088803088803089}`
- Longest consecutive underperform vs SPY: **9 months** (2006-08 → 2007-04); months underperform pct=55.98%

## Interpretation

- Pass does **not** require D+C to beat A on CAGR/Sharpe every period.
- Require mild CAGR lag, majority DD improvement, intact OOS, not solely 2008-driven, stable costs/neighborhood, clean PIT.

