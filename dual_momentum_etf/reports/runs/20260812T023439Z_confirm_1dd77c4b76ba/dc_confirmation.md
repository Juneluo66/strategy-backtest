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

## Relative-to-SPY audit (do not conflate A/B/C)

### Legacy clarification

- The previously reported '相对SPY最长连续跑输9个月' was Metric A only (longest consecutive single-month return underperformance = 9 months). It is NOT relative-NAV opportunity-cost duration and must not be read as 'investors only endure 9 months of opportunity cost'.
- Prior code: `confirmation.longest_underperform_streak_months`
- Formula: `month_ret_dc = prod(1+daily_net)-1 by Period[M]; streak where month_ret_dc < month_ret_spy`

### Metric A — longest consecutive **single-month return** below SPY

- Definition: Longest consecutive calendar months where (1+r_daily).prod()-1 for D+C is strictly less than the same for SPY. NOT relative-NAV underwater duration.
- Longest streak: **9 months** (2006-08 → 2007-04)
- Share of months under: 55.98%

### Metric B — longest streak of trailing **12-month return** below SPY

- Definition: At each month-end, compare trailing 12-month compounded returns. Longest consecutive months with R12(DC) < R12(SPY).
- Longest streak: **38 months** (2012-07 → 2015-08)
- Share of months under: 62.93%

### Metric C — **relative NAV** opportunity-cost intervals

- Definition: relative_nav_t = nav_dc_t / nav_spy_t (both rebased to 1 at common start). An opportunity-cost interval starts when relative_nav falls below its historical high and ends when it recovers to/above that high; open intervals at sample end are ongoing.
- Max relative drawdown: **-73.37%**
- Current relative drawdown: **-69.04%**
- Months since last relative-NAV high: **210** (peak `2009-03-09`, sample end `2026-08-10`)
- Rolling win rate vs SPY (DC trailing return > SPY): 3y=23.77%, 5y=20.10%, 10y=20.86%
- Longest relative-NAV underwater: **210 months** | start `2009-03-10` | trough `2024-12-24` (dd -73.37%) | recovery `NONE` | **ongoing**

- Chart: `/home/ec2-user/strategy-backtest/dual_momentum_etf/reports/relative_nav_drawdown.png`

### Alignment (D+C vs SPY)

- Price basis: Yahoo Adj Close (dividend/split adjusted) via load_ohlc; Open scaled by AdjClose/Close
- D+C field: equity.net_return (after one-way costs; next-open execution)
- SPY field: buy-and-hold Adj Close daily pct_change; zero cost; always invested
- Timing: D+C uses month-end close signal → next session open fill; SPY BH is continuous close-to-close. This is intentional strategy-vs-market comparison, not same execution clock.
- SPY BH vs Adj Close daily corr=1.00, max abs diff=0.0

### Paper-trading engineering freeze

- config_hash: `1dd77c4b76bad4fe005e3cec2bf8f3a84471850055c58fc7f1afe6f246993043`
- git_commit: `unavailable`
- data retrieved_at: `2026-08-11T11:17:52.623219+00:00`
- rebalance signal audit CSV: `/home/ec2-user/strategy-backtest/dual_momentum_etf/reports/runs/20260812T023439Z_confirm_1dd77c4b76ba/dc_rebalance_signal_audit.csv` (483 rows)
- SGOV/BIL sleeve audit: **PASS** issues=[]
- IBKR constraints: `PAPER_TRADING_BLOCKED_UNTIL_BROKER_CONSTRAINTS_IMPLEMENTED` (fractional/min commission/notional = NOT_MODELED in research engine)

## Interpretation

- Pass does **not** require D+C to beat A on CAGR/Sharpe every period.
- Require mild CAGR lag, majority DD improvement, intact OOS, not solely 2008-driven, stable costs/neighborhood, clean PIT.
- Do **not** interpret Metric A (single-month streak) as investor opportunity-cost duration; use Metric C.

