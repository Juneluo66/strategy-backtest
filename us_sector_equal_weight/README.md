# US Sector Equal-Weight Rebalancing

Independent research track for **sector equal-weight rebalancing** on the nine
1998 Select Sector SPDRs. This is **not** sector-momentum retuning.

## Frozen rules

- Universe: XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY
- Weights: always 1/9 (no ranking, Top-N, SMA, BIL, vol-weight, leverage)
- Versions only: `EW9_monthly`, `EW9_quarterly`, `EW9_annual`
- Signal → next open; cost 5 bp one-way (stress 10/20)
- Discovery ETF sample labeled `DISCOVERY_SAMPLE` (secondary observation from sector_momentum)

## Commands

```bash
cd strategy-backtest/us_sector_equal_weight
pip install -e .
us-sector-ew fetch
us-sector-ew full-audit
```

## Hard constraints

- Do not modify IBKR
- Do not promote sector-momentum buffer
- Do not retune sector momentum
- Do not claim guaranteed profits
