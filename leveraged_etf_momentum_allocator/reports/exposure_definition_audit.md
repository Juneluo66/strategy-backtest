# Exposure Definition Audit

## CRITICAL FINDING

Phase 5 label `ROBUST_CORE_1_5X` was implemented as **return scaling**:

```python
equity["net_return"] = equity["net_return"] * 0.5
```

That is **portfolio exposure scaling of the already-levered ETF strategy**,
economically equivalent to holding **~50% NAV in the signal's 3x ETF** and
**~50% cash/BSV**, yielding **underlying equity beta ≈ 1.5**.

It is **NOT**:

- `SetHoldings(TQQQ, 1.5)` → would target ~**4.5x** QQQ beta
- replacing 3x ETFs with synthetic 1.5x ETFs
- a free IBKR margin leverage scalar independent of ETF leverage

## Two layers of leverage

| Layer | Meaning |
|-------|---------|
| A. Portfolio weight | Fraction of account NAV in an ETF |
| B. ETF internal leverage | Daily target beta of the ETF itself (e.g. TQQQ ≈ 3x) |

Effective underlying exposure ≈ **weight × ETF_beta**.

## Paper V1 definition

- Metric: `underlying_equity_beta`
- Target: **1.5**
- For TQQQ/TECL/SPXL/TECS (|β|≈3): **portfolio weight = 0.50**, remainder **BSV**
- UVXY: **PAPER_EXECUTION_OVERLAY**, max weight **25%** (not equity-beta scaled)

## Historical reference mapping

| Label | Implementation | Approx underlying β |
|-------|----------------|---------------------|
| ROBUST_CORE_3X_ORIGINAL | 100% weight in 3x ETF | ~3.0 |
| ROBUST_CORE_2X | return × (2/3) ≡ weight ≈ 66.7% | ~2.0 |
| ROBUST_CORE_1_5X | return × 0.5 ≡ weight ≈ 50% | ~1.5 |
| ROBUST_CORE_1X | return × (1/3) ≡ weight ≈ 33.3% | ~1.0 |

## IBKR / margin note

Holding 50% TQQQ + 50% BSV is typically a **long-only, unlevered portfolio
at the broker level** (no Reg-T margin leverage). The 1.5x is entirely from
the ETF product's embedded leverage × half weight — not account leverage.

`SetHoldings(TQQQ, 1.5)` would require margin and produce a different risk
profile; **Paper V1 forbids that construction**.
