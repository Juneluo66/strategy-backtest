# Non-OHLCV validation

- Data source: **Eastmoney margin + SSE/SZSE daily ETF shares (free; no TuShare)**
- Source version: `free_20260804T110028Z`
- Coverage date range: `2011-12-05` → `2026-08-03`
- Max ETF codes with raw values (any field): **49**
- Status: **BLOCKED_BY_DATA**
- Unblock BLOCKED_BY_DATA: **no**

## Raw field checks

| field       |   rows |   codes | date_min   | date_max   |   missing_ratio_on_grid |   max_gap_sessions | unit_ok   | pit_ok   |   lookahead_violations | notes                                                    |
|:------------|-------:|--------:|:-----------|:-----------|------------------------:|-------------------:|:----------|:---------|-----------------------:|:---------------------------------------------------------|
| rzye        |  73694 |      47 | 2011-12-05 | 2026-08-03 |                  0.2413 |                882 | True      | True     |                      0 | missing_ratio_on_grid=0.2413 >= 0.05                     |
| rzmre       |  73694 |      47 | 2011-12-05 | 2026-08-03 |                  0.2413 |                882 | True      | True     |                      0 | missing_ratio_on_grid=0.2413 >= 0.05                     |
| total_share |  95956 |      49 | 2012-01-04 | 2026-07-27 |                  0.0453 |                  6 | True      | True     |                      0 | total_share unit is 万份 per TuShare etf_share_size docs |

## Factor production gate (`missing_ratio < 0.05` and `available_at <= signal_date`)

| factor           |   missing_ratio |   codes_with_values | date_min   | date_max   | pit_ok   | production_eligible   | notes                        |
|:-----------------|----------------:|--------------------:|:-----------|:-----------|:---------|:----------------------|:-----------------------------|
| MARGIN_BUY_RATIO |          0.2417 |                  47 | 2005-02-23 | 2026-07-27 | True     | False                 | missing_ratio=0.2417 >= 0.05 |
| MARGIN_CHG_10D   |          0.246  |                  47 | 2005-02-23 | 2026-07-27 | True     | False                 | missing_ratio=0.2460 >= 0.05 |
| SHARE_CHG_5D     |          0.0476 |                  49 | 2005-02-23 | 2026-07-27 | True     | True                  |                              |
| SHARE_CHG_20D    |          0.0546 |                  49 | 2005-02-23 | 2026-07-27 | True     | False                 | missing_ratio=0.0546 >= 0.05 |

## Possible differences versus QMT

- QMT local bridge timestamps and revision handling are unpublished; next-session 08:30 is a conservative public proxy.
- Exchange/Eastmoney share units are 份; TuShare etf_share_size uses 万份; relative SHARE_CHG is unit-invariant if consistent.
- margin coverage is exchange margin-target history; ETFs absent from a day remain missing (not zero).
- Adjustment and overseas QDII share timing differ; A_SHARE_ONLY still excludes QDII from trading.

## Notes

- Keeping BLOCKED_BY_DATA; production parquet promotion refused.

Empty downloads never write production parquet. Missing inputs stay NaN (never zero-filled). Quarterly fund-scale pages are not used.
