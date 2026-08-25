# Data audit

|   symbols |   passed |   failed |   partial_factors |
|----------:|---------:|---------:|------------------:|
|        49 |       49 |        0 |                 4 |

## Required controls

- Signal factors use T-close data; execution is scheduled for the next available session open.
- `qfq` adjustment is used consistently for stored OHLCV. Vendor adjustment revisions remain a limitation.
- QDII is excluded from trading in `A_SHARE_ONLY`; its overseas close timing is therefore never used for a trade signal.
- Zero volume/amount rows are recorded as suspension-like observations and are not silently converted into fills.
- Listing date is the first vendor-available bar proxy, not a fund-contract primary source.

## Partial non-OHLCV factors

| factor           | source_path                                                                                 | status              |   missing_ratio |   affected_dates | note                                                                |
|:-----------------|:--------------------------------------------------------------------------------------------|:--------------------|----------------:|-----------------:|:--------------------------------------------------------------------|
| MARGIN_BUY_RATIO | /home/ec2-user/strategy-backtest/etf_rotation/data/cache/non_ohlcv/MARGIN_BUY_RATIO.parquet | partial_unavailable |               1 |             5207 | No cached source; C1/C4 are partial and cannot be full replication. |
| MARGIN_CHG_10D   | /home/ec2-user/strategy-backtest/etf_rotation/data/cache/non_ohlcv/MARGIN_CHG_10D.parquet   | partial_unavailable |               1 |             5207 | No cached source; C1/C4 are partial and cannot be full replication. |
| SHARE_CHG_5D     | /home/ec2-user/strategy-backtest/etf_rotation/data/cache/non_ohlcv/SHARE_CHG_5D.parquet     | partial_unavailable |               1 |             5207 | No cached source; C1/C4 are partial and cannot be full replication. |
| SHARE_CHG_20D    | /home/ec2-user/strategy-backtest/etf_rotation/data/cache/non_ohlcv/SHARE_CHG_20D.parquet    | partial_unavailable |               1 |             5207 | No cached source; C1/C4 are partial and cannot be full replication. |

A partial factor set is never labelled a complete v8 replication.
