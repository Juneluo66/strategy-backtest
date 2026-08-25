# US Sector ETF Momentum (independent research track)

Cross-sectional momentum on the **nine 1998 Select Sector SPDRs**.  
Primary objective: **long-run terminal wealth vs SPY** (not low drawdown / high cash).

**No** rule inheritance from D+C, 80/20, half_protect, or multi_asset_etf_trend.

## Universe

XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY  
Benchmarks: SPY BH, QQQ BH, nine-sector equal-weight monthly  
Forbidden: XLRE, XLC, leverage ETFs, dropping historical losers

## Pre-registered versions (only)

1. `base_12_1_top3`
2. `composite_6_1_12_1_top3` (sole return challenger)
3. `composite_top3_buffer`

## Commands

```bash
cd /home/ec2-user/strategy-backtest/us_sector_momentum
python3 -m pip install -e '.[dev]'
us-sector-momentum fetch
us-sector-momentum audit-data
us-sector-momentum full-audit
pytest -q
```

Existing Yahoo caches are reused via sibling symlinks; only missing symbols (e.g. XLB, ^IRX) are downloaded.

## Outputs

- `reports/sector_momentum_audit.md`
- `reports/sector_momentum_metrics.csv`
- `reports/sector_momentum_rolling.csv`
- `reports/sector_momentum_sector_contributions.csv`
- `reports/sector_momentum_fixed_endpoints.csv`
- `reports/sector_momentum_bootstrap.csv`

Gate: `SECTOR_MOMENTUM_RETURN_CANDIDATE` or `REJECTED`.  
IBKR modified: **false**.
