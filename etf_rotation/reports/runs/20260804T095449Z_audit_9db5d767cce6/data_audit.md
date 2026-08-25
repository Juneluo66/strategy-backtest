# Data audit

|   symbols |   passed |   failed |   partial_factors |
|----------:|---------:|---------:|------------------:|
|        49 |       49 |        0 |                 4 |

## Required controls

- Signal factors use T-close data; execution is scheduled for the next available session open.
- Adjustment/source basis is shown per symbol. Sina fallback is unadjusted and blocks a clean qfq-equivalent comparison.
- QDII is excluded from trading in `A_SHARE_ONLY`; its overseas close timing is therefore never used for a trade signal.
- Zero volume/amount rows are recorded as suspension-like observations and are not silently converted into fills.
- Listing date is the first vendor-available bar proxy, not a fund-contract primary source.

## Partial non-OHLCV factors

| factor           | source_path                                                                                 | status              |   missing_ratio |   affected_dates | note                                                                                                                                                                                                                                                                                                                 |
|:-----------------|:--------------------------------------------------------------------------------------------|:--------------------|----------------:|-----------------:|:---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| MARGIN_BUY_RATIO | /home/ec2-user/strategy-backtest/etf_rotation/data/cache/non_ohlcv/MARGIN_BUY_RATIO.parquet | partial_unavailable |               1 |             5207 | Exchange margin detail (SSE/SZSE via AkShare) is a candidate raw source, but no versioned PIT parquet is wired; absent codes stay missing (not zero). See reports/non_ohlcv_source_research.md.                                                                                                                      |
| MARGIN_CHG_10D   | /home/ec2-user/strategy-backtest/etf_rotation/data/cache/non_ohlcv/MARGIN_CHG_10D.parquet   | partial_unavailable |               1 |             5207 | Same as MARGIN_BUY_RATIO: rzye day-detail candidate exists, production cache not enabled without calendar available_at + coverage audit. See reports/non_ohlcv_source_research.md.                                                                                                                                   |
| SHARE_CHG_5D     | /home/ec2-user/strategy-backtest/etf_rotation/data/cache/non_ohlcv/SHARE_CHG_5D.parquet     | partial_unavailable |               1 |             5207 | Daily ETF share history requires TuShare etf_share_size/QMT; no audited tokenized dump. Quarterly scale pages cannot build 5D changes. See reports/non_ohlcv_source_research.md. | No TUSHARE_TOKEN / QMT share dump. Quarterly fund-scale pages cannot support SHARE_CHG_5D/20D. Keep factors partial_unavailable.  |
| SHARE_CHG_20D    | /home/ec2-user/strategy-backtest/etf_rotation/data/cache/non_ohlcv/SHARE_CHG_20D.parquet    | partial_unavailable |               1 |             5207 | Daily ETF share history requires TuShare etf_share_size/QMT; no audited tokenized dump. Quarterly scale pages cannot build 20D changes. See reports/non_ohlcv_source_research.md. | No TUSHARE_TOKEN / QMT share dump. Quarterly fund-scale pages cannot support SHARE_CHG_5D/20D. Keep factors partial_unavailable. |

A partial factor set is never labelled a complete v8 replication.

Research notes: `reports/non_ohlcv_source_research.md`. Status remains `BLOCKED_BY_DATA` until all four factors have `missing_ratio < 0.05` under audited PIT sources.
