# Data Adjustment Audit

> **Status:** WARNING — Yahoo Adj Close used; QuantConnect normalization not byte-identical

## Price Source

| Item | Value |
|------|-------|
| Vendor | Yahoo Finance via `yfinance` |
| Field for signals | `Adj Close` (total-return adjusted) |
| Field for execution | `Adj Close` (same series) |
| Open adjustment | `Open * (Adj Close / Close)` |

## Per-Asset Notes

| Ticker | Inception (local) | Adjustment | Risk |
|--------|-------------------|------------|------|
| SPY | 2010-01-04 | Adj Close | LOW |
| QQQ | 2010-01-04 | Adj Close | LOW |
| TQQQ | 2010-02-11 | Adj Close | MEDIUM — leveraged reset |
| UVXY | 2011-10-04 | Adj Close | **HIGH** — reverse splits; Yahoo levels not QC-equivalent |
| TECL | 2010-01-04 | Adj Close | MEDIUM |
| SPXL | 2010-01-04 | Adj Close | MEDIUM |
| SQQQ | 2010-02-11 | Adj Close (signal only) | MEDIUM |
| TECS | 2010-01-04 | Adj Close | MEDIUM |
| BSV | 2010-01-04 | Adj Close | LOW |

## UVXY Reverse Splits

Yahoo `Adj Close` for UVXY preserves daily **returns** reasonably for RSI, but absolute price levels are not comparable to QuantConnect. UVXY branch PnL and holding attribution carry **HIGH RISK** flags.

## Effective Start Reconciliation

| Field | Date |
|-------|------|
| Code `SetStartDate` | 2012-01-01 |
| Local effective start | 2012-07-20 |
| Reason | `max(ETF inceptions) + SetWarmUp(200)` — UVXY inception 2011-10-04 + 200 sessions |

## SOURCE_DATE_RECONCILIATION

- **Code requested start:** 2012-01-01
- **Observed first usable date:** 2012-07-20 (local)
- **Website reported interval:** ~2016-01 to 2025-12 (index card)
- **Possible explanations (evidence only):**
  - ETF inception / warm-up
  - Page reporting convention (display window ≠ code start)
  - Updated backtest on QuantConnect
  - Strategy version difference

## Verdict

**DATA ADJUSTMENT: WARNING** — replication close to website CAGR/MaxDD but not exact; UVXY/SQQQ adjustment semantics require QC data feed for full match.
