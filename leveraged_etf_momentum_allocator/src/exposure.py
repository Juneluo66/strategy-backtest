"""Paper V1 exposure construction — underlying equity beta, not ETF weight folklore.

CRITICAL:
Phase 5 ROBUST_CORE_1_5X multiplied daily strategy returns by 0.5. That is
economically equivalent to holding ~50% of NAV in a ~3x ETF and ~50% cash/BSV
(underlying beta ≈ 1.5), NOT SetHoldings(TQQQ, 1.5) which would be ~4.5x beta.
"""
from __future__ import annotations

from typing import Any, Optional

# Nominal daily equity betas used for position sizing (research convention)
DEFAULT_ASSET_BETA: dict[str, Optional[float]] = {
    "TQQQ": 3.0,
    "TECL": 3.0,
    "SPXL": 3.0,
    "TECS": -3.0,
    "SQQQ": -3.0,
    "BSV": 0.0,
    "SPY": 1.0,
    "QQQ": 1.0,
    "CASH": 0.0,
    "UVXY": None,  # not an equity-beta product
}


def target_weight_for_beta(
    raw_target: str,
    *,
    target_underlying_beta: float = 1.5,
    asset_beta: Optional[dict[str, Optional[float]]] = None,
    uvxy_max_weight: float = 0.25,
    defensive: str = "BSV",
) -> dict[str, Any]:
    """Map raw signal target → portfolio weights under Paper V1 exposure definition.

    Returns weights that sum to 1.0 (cash sleeve via defensive ticker or CASH).
    """
    betas = dict(DEFAULT_ASSET_BETA)
    if asset_beta:
        betas.update(asset_beta)

    raw = raw_target.upper() if raw_target else "BSV"
    if raw == "CASH":
        return {
            "raw_target": raw,
            "paper_target": "CASH",
            "weights": {"CASH": 1.0},
            "implied_underlying_beta": 0.0,
            "overlay": None,
            "three_x_etf_weight": 0.0,
        }

    if raw == "UVXY":
        w = min(float(uvxy_max_weight), 1.0)
        rem = 1.0 - w
        return {
            "raw_target": raw,
            "paper_target": "UVXY",
            "weights": {"UVXY": w, defensive: rem},
            "implied_underlying_beta": None,
            "overlay": "PAPER_EXECUTION_OVERLAY",
            "three_x_etf_weight": w,
            "uvxy_cap_applied": w < 1.0,
        }

    beta = betas.get(raw)
    if beta is None:
        # Unknown — fully defensive
        return {
            "raw_target": raw,
            "paper_target": defensive,
            "weights": {defensive: 1.0},
            "implied_underlying_beta": 0.0,
            "overlay": None,
            "three_x_etf_weight": 0.0,
        }

    abs_beta = abs(float(beta))
    if abs_beta < 1e-12:
        return {
            "raw_target": raw,
            "paper_target": raw,
            "weights": {raw: 1.0},
            "implied_underlying_beta": 0.0,
            "overlay": None,
            "three_x_etf_weight": 0.0,
        }

    # weight * asset_beta ≈ target_underlying_beta (sign preserved via asset)
    # For |beta|=3 and target=1.5 → weight=0.5
    w = min(abs(float(target_underlying_beta)) / abs_beta, 1.0)
    rem = 1.0 - w
    weights = {raw: w}
    if rem > 1e-12:
        weights[defensive] = rem

    implied = float(beta) * w  # signed
    return {
        "raw_target": raw,
        "paper_target": raw,
        "weights": weights,
        "implied_underlying_beta": implied,
        "overlay": None,
        "three_x_etf_weight": w if abs_beta >= 2.5 else 0.0,
    }


def exposure_audit_text() -> str:
    return """# Exposure Definition Audit

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
"""
