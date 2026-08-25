# Implementation Reconciliation — QC 0.838 vs Local 1.22

## Judgment: `NO_LOCAL_TIMESTAMP_INFLATION__SIGNALS_~90PCT_AGREE__1_22_VS_0_838_MOSTLY_ENGINE_SAMPLE_RF_COSTS_NOT_WEEKEND_BUG`

## Specs

### QC (research 21195)
- Bitfinex BTCUSD Daily + SMA50 + ROC20
- DateRules.WeekStart(QQQ) + TimeRules.At(8,0) ET
- set_holdings(..., 1, True)
- Reported Sharpe: strategy `0.838`, QQQ `0.682`, SPY `0.564`

### Local prior audit
- Yahoo BTC-USD
- ISO week last equity session
- next session close-to-close
- Adj Close, 0 bps

## BTC price source (Yahoo vs Bitfinex)

- Common days: `4350`
- Median |%| diff: `0.152%`
- P95 |%| diff: `1.396%`
- Max |%| diff: `10.920%`
- Corr(log returns): `0.9885`

## Weekly signal agreement

- Weeks compared: `615` (2014-11-10 → …)
- **Agree(QC Bitfinex week-start vs our weekend→next-week): `90.24%`**
- Agree(QC Bitfinex vs QC-timing on Yahoo): `98.86%`
- Disagreement weeks: `60`

### Disagreement weeks (first 40)

| WeekStart | Ours decision (Fri) | QC BTC asof | Ours | QC-BF | QC-YH |
|---|---|---|---:|---:|---:|
| 2014-11-24 | 2014-11-21 | 2014-11-23 | False | True | True |
| 2014-12-08 | 2014-12-05 | 2014-12-07 | True | False | False |
| 2015-02-23 | 2015-02-20 | 2015-02-22 | True | False | False |
| 2015-03-23 | 2015-03-20 | 2015-03-22 | True | False | False |
| 2015-05-18 | 2015-05-15 | 2015-05-17 | True | False | False |
| 2015-08-10 | 2015-08-07 | 2015-08-09 | True | False | False |
| 2015-11-23 | 2015-11-20 | 2015-11-22 | True | False | False |
| 2016-01-11 | 2016-01-08 | 2016-01-10 | False | True | True |
| 2016-04-04 | 2016-04-01 | 2016-04-03 | False | True | True |
| 2016-04-11 | 2016-04-08 | 2016-04-10 | False | True | True |
| 2016-05-16 | 2016-05-13 | 2016-05-15 | True | False | False |
| 2016-07-05 | 2016-07-01 | 2016-07-04 | True | False | False |
| 2016-07-18 | 2016-07-15 | 2016-07-17 | False | True | True |
| 2016-09-26 | 2016-09-23 | 2016-09-25 | True | False | False |
| 2017-06-26 | 2017-06-23 | 2017-06-25 | True | False | False |
| 2017-10-02 | 2017-09-29 | 2017-10-01 | False | True | True |
| 2017-11-13 | 2017-11-10 | 2017-11-12 | True | False | True |
| 2019-01-07 | 2019-01-04 | 2019-01-06 | False | True | True |
| 2019-02-11 | 2019-02-08 | 2019-02-10 | False | True | False |
| 2019-02-19 | 2019-02-15 | 2019-02-18 | False | True | True |
| 2019-03-18 | 2019-03-15 | 2019-03-17 | False | True | True |
| 2019-06-10 | 2019-06-07 | 2019-06-09 | True | False | False |
| 2019-07-15 | 2019-07-12 | 2019-07-14 | True | False | False |
| 2019-08-05 | 2019-08-02 | 2019-08-04 | False | True | True |
| 2019-10-28 | 2019-10-25 | 2019-10-27 | False | True | True |
| 2020-05-26 | 2020-05-22 | 2020-05-25 | True | False | False |
| 2020-06-01 | 2020-05-29 | 2020-05-31 | False | True | True |
| 2020-08-24 | 2020-08-21 | 2020-08-23 | False | True | True |
| 2020-10-12 | 2020-10-09 | 2020-10-11 | False | True | True |
| 2020-12-14 | 2020-12-11 | 2020-12-13 | False | True | True |
| 2021-03-01 | 2021-02-26 | 2021-02-28 | True | False | False |
| 2021-04-12 | 2021-04-09 | 2021-04-11 | False | True | True |
| 2021-04-19 | 2021-04-16 | 2021-04-18 | True | False | False |
| 2021-05-10 | 2021-05-07 | 2021-05-09 | False | True | True |
| 2021-07-26 | 2021-07-23 | 2021-07-25 | False | True | True |
| 2021-09-20 | 2021-09-17 | 2021-09-19 | False | True | True |
| 2022-02-14 | 2022-02-11 | 2022-02-13 | False | True | True |
| 2022-03-21 | 2022-03-18 | 2022-03-20 | True | False | False |
| 2023-02-27 | 2023-02-24 | 2023-02-26 | False | True | True |
| 2023-05-01 | 2023-04-28 | 2023-04-30 | True | False | False |
| … | (20 more) | | | | |

## P&L / Sharpe impact of signal disagreement

- Days with different holdings: `290` (`9.79%`)
- Cum wealth gap (full path ours/qc − 1): `-20.29%`
- Cum gap on differ-days only: `-21.86%`
- Sharpe ours (same engine): `1.221`
- Sharpe QC-timing Bitfinex (same Adj/0bps engine): `1.362`
- **ΔSharpe from timing/signal alone: `-0.141`**

## Factorizing 1.22 → 0.838

| Variant | Sharpe |
|---|---:|
| QC reported strategy | 0.838 |
| Local ours (weekend Yahoo Adj 0bps) | 1.221 |
| Local QC-proxy Bitfinex week-start Adj 0bps | 1.362 |
| Local QC-proxy Close+open-fill 0bps | 1.291 |
| Local QC-proxy Close+open-fill 5bps | 1.241 |
| Local QC-proxy Adj + rf 2% | 1.199 |
| Local BH QQQ Adj | 0.782 |
| Local BH QQQ Adj + rf 2% | 0.637 |
| Local BH QQQ Close | 0.867 |
| QC reported BH QQQ | 0.682 |

- Strat/QQQ Sharpe ratio QC reported: `1.229`
- Strat/QQQ Sharpe ratio local ours: `1.561`
- Strat/QQQ Sharpe ratio local QC-proxy: `1.741`

### Decomposition reading

1. **Timestamp/schedule**: weekend decision vs Mon 08:00 ET week-start (weekend BTC moves).
2. **BTC source**: Yahoo vs Bitfinex (see median/P95 diffs; QC-Yahoo vs QC-Bitfinex agreement).
3. **QQQ/SHY total return**: Adj Close vs raw Close (dividends).
4. **Costs**: 0 vs ~IBKR/LEAN friction (proxy 5 bps RT).
5. **Sharpe definition / sample / rf**: BH QQQ local vs QC 0.682 is the level-shift diagnostic.

### Headline answer on 1.22 vs 0.838

- Local weekend timing does **not** inflate Sharpe vs QC week-start proxy (ΔSharpe timing alone = `-0.141`).
- Signal agreement is high (~90%); residual gaps are mostly weekend BTC path.
- Absolute Sharpe gap vs QC *reported* 0.838 remains after close/open/5bps; treat QC 0.838 as the implementation-faithful headline, local ~1.2x as engine-comparable.
- **Do not downgrade for timestamp bug.** Do **not** promote local 1.22 as QC-equivalent.

## Absolute stats (local engine)

- `ours_weekend_yahoo_adj_0bps`: Sharpe `1.221` CAGR `15.05%` Vol `12.11%` MaxDD `-16.24%`
- `qc_weekstart_bitfinex_adj_0bps`: Sharpe `1.362` CAGR `17.29%` Vol `12.29%` MaxDD `-16.24%`
- `qc_weekstart_bitfinex_close_openfill_0bps`: Sharpe `1.291` CAGR `15.46%` Vol `11.70%` MaxDD `-13.35%`
- `qc_weekstart_bitfinex_close_openfill_5bps`: Sharpe `1.241` CAGR `14.81%` Vol `11.70%` MaxDD `-13.44%`
- `bh_qqq_adj`: Sharpe `0.782` CAGR `12.09%` Vol `21.77%` MaxDD `-30.19%`
- `bh_qqq_close`: Sharpe `0.867` CAGR `17.93%` Vol `21.87%` MaxDD `-35.62%`
- `bh_spy_adj`: Sharpe `0.831` CAGR `10.61%` Vol `17.37%` MaxDD `-21.14%`
- `bh_spy_close`: Sharpe `0.728` CAGR `11.88%` Vol `17.60%` MaxDD `-34.10%`

## Downgrade rule

Downgrade only if `TIMESTAMP_OR_SIGNAL_MISMATCH_MATERIAL_DOWNGRADE_RISK` (local timing *inflates* Sharpe and agreement is poor).

Current result: signals mostly agree; local weekend path is *slightly worse* than QC week-start proxy → **no timestamp-bug downgrade**. Quote QC **0.838** as implementation-faithful; keep local ~1.2 for within-engine diagnostics only.
