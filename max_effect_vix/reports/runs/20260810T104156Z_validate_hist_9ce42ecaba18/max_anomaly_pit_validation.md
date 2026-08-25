# MAX anomaly historical S&P500 validation

## Status labels

- `DATA_TIER`: `HISTORICAL_SP500_APPROX`
- `SURVIVORSHIP_BIAS`: `REDUCED_NOT_ELIMINATED`
- `PIT_VALIDATED`: `False`
- `SIZE_NEUTRAL`: `BLOCKED_BY_PIT_MARKET_CAP`
- `DELISTING_RETURN`: `UNAVAILABLE`

## 1. Data source

Wikipedia historical S&P 500 constituent changes + Yahoo Finance adjusted OHLCV.
Kenneth French factors used when downloadable; otherwise factor regression is marked unavailable.

## 2. Universe construction

Membership at each formation date is reconstructed by reversing recorded Wikipedia
add/remove events from the current constituent snapshot. The Wikipedia change table
is incomplete, so this only reduces current-constituent backfill bias.

Membership audit rows: 24.

## 3. PIT handling

`PIT_VALIDATED` is false. No point-in-time market caps, no CRSP security master,
and no full-market investable universe.

## 4. Delisting handling

Index exits are retained through the exit date, then forced liquidated with an
`INDEX_EXIT` audit row. True CRSP delisting returns are unavailable;
last traded prices may act only as `DELIST_PROXY` and are labeled as such.
Recorded index-exit events: 252.

## 5. Signal definition

MAX5 = mean of the top 5 daily returns over the prior 21 completed trading days.
Vol/beta residualization uses only pre-formation price history.

## 6. Portfolio construction

Lowest MAX decile, capped at 25 names, equal weight. Signal at prior close;
execution at next session open.

## 7. Transaction cost

Default 5 bp one-way on measured turnover, plus financing/borrow assumptions from frozen config.

## 8. Turnover

- one_way_turnover: 113.9
- annualized_turnover: 9.905232142857143

## 9. Factor exposures

- Gross Sharpe: 0.6647747014635251
- After-cost Sharpe: 0.5991724196496808
- Mean monthly Spearman IC: 0.010577484578086388
- Fama-MacBeth MAX slope: 0.2359667237756293 (t=1.6215261683085926)
- Size in Fama-MacBeth: `BLOCKED_BY_PIT_MARKET_CAP`
- Factor alpha (monthly): None (t=None)
- Factor loadings: {}
- QMJ: NOT_AVAILABLE

## 10. Limitations

- Wikipedia S&P 500 change history is incomplete.
- SURVIVORSHIP_BIAS remains REDUCED_NOT_ELIMINATED, not eliminated.
- PIT_VALIDATED is false; no CRSP/Compustat point-in-time fundamentals.
- Size neutralization is BLOCKED_BY_PIT_MARKET_CAP.
- Index exit is not a CRSP delisting return; DELISTING_RETURN=UNAVAILABLE.
- Yahoo prices omit a complete delisting file and may miss dead tickers.

## Gate decision

Independent-alpha claim requires PIT market caps, full delisting returns, and
`PIT_VALIDATED=true`. This run cannot clear that gate.
