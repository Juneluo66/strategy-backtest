# US Sector Equal-Weight — Project Status

- Discovery sample: `1998-12-22` → `2026-08-12` (**DISCOVERY_SAMPLE**)
- Gate: **`DISCOVERY_ONLY`** (9/13) — **not** `SECTOR_EQUAL_WEIGHT_RETURN_CANDIDATE`
- Discovery monthly net CAGR beats SPY, but **0/5** pre-registered post-discovery starts beat SPY
- Rolling 5y / 10y win rates vs SPY below gates (≈52%)
- On RSP span, EW9 ≈ RSP → **general equal-weight exposure**, not clear sector-allocation alpha
- Monthly does **not** beat quarterly/annual after costs → prefer **lower-turnover** quarterly/annual if studied further (do not pick by max CAGR)
- French 12-industry mechanism check: pre/post ETF EW paths positive (non-tradable validation only)
- Cap-weight PIT proxy: **NOT_COMPUTED**
- IBKR: **not modified**
- Sector momentum: **not retuned**; buffer **not** promoted
- Report: `reports/sector_equal_weight_audit.md`

```bash
cd strategy-backtest/us_sector_equal_weight
pip install -e .
us-sector-ew fetch
us-sector-ew full-audit
```
