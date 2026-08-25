# PAPER_TRADING_PLAN — PAPER_V1

> **Status:** PAPER_TRADING_CANDIDATE — FORWARD ACTIVE  
> **Frozen date:** 2026-08-24  
> **Immutable:** any change → PAPER_V2+

---

## Frozen strategy

| Field | Value |
|-------|-------|
| Version | **PAPER_V1** |
| Base tree | **ABLATION_DROP_SPY_RSI** |
| Thresholds | Standardized natural only (30/70/80) |
| Ablation | `drop_spy_rsi: true` |
| Parameter changes | **NO** |
| Tree changes | **NO** |
| Universe changes | **NO** |
| Retroactive log rewrite | **NO** |

Config: `configs/paper_v1.yaml`  
Manifest: `reports/paper_v1_manifest.md`  
Hashes: `reports/runs/paper_v1/hashes.json`

---

## Exposure definition (CRITICAL)

Phase 5 `ROBUST_CORE_1_5X` was **return × 0.5**, not `SetHoldings(1.5)`.

Paper V1 implements the equivalent **underlying equity beta** construction:

| Concept | Value |
|---------|-------|
| Metric | `underlying_equity_beta` |
| Target | **1.5** |
| 3x ETF portfolio weight | **50%** |
| Defensive sleeve | **50% BSV** |
| UVXY max weight | **25%** (`PAPER_EXECUTION_OVERLAY`) |

**Forbidden:** 150% weight in TQQQ (≈4.5x beta).

Detail: `reports/exposure_definition_audit.md`

---

## Execution timing

| Step | Timing |
|------|--------|
| Indicators / signal | Daily **close** |
| Order | Next session |
| Fill | Next market **open** |
| Same-close fill | **Forbidden** |

Mode: `NEXT_OPEN_CONSERVATIVE`

---

## Cost assumptions

| Case | Total bps | Role |
|------|-----------|------|
| **Base (official NAV)** | **5** | Paper V1 |
| Shadow | 0 | Reporting only |
| Shadow | 10 | Reporting only |
| Shadow | 25 | Reporting only |

---

## Risk overlays

| Overlay | Rule | Label |
|---------|------|-------|
| Equity 3x ETF | weight = 1.5 / 3 = 0.50 | Exposure definition |
| Inverse 3x (TECS) | weight = 0.50 | Exposure definition |
| UVXY | max weight 25%, rest BSV | **PAPER_EXECUTION_OVERLAY** (does not change signal) |

---

## Benchmarks / shadows

| ID | Description | Official? |
|----|-------------|-----------|
| SHADOW_C | Paper V1 reduced exposure | **YES** |
| SHADOW_A | ORIGINAL full 3x weights | No |
| SHADOW_B | Robust core full ETF exposure | No |
| SHADOW_D | TQQQ buy & hold | No |
| SHADOW_E | SPY buy & hold | No |

Logs: `logs/paper_signals.csv`, `logs/paper_daily_metrics.csv`, `logs/paper_shadows.csv`

---

## Stop conditions

| Class | Examples | Action |
|-------|----------|--------|
| DATA_FAILURE | indicator mismatch, CA failure, missing ticker | Pause; investigate; do not retune |
| EXECUTION_FAILURE | cannot fill; slippage >> model | Pause ops; do not retune |
| MODEL_WARNING | rolling underperformance | Document only |

Forward windows to record: **30 / 90 / 180** days.  
Short-term losses **do not** authorize parameter changes.

---

## Versioning policy

1. PAPER_V1 is immutable after freeze.  
2. Any logic/config/universe/exposure change → **PAPER_Vn** with new `frozen_date`.  
3. New version starts a **new** forward clock.  
4. Signal log is **append-only**; hash mismatch aborts PAPER_V1 runs.

---

## Live readiness gate

PAPER_V1 must **not** go live on backtest strength alone.

Minimum:

- ≥ **6 months** forward data (preferably ≥ **12 months**)
- ≥ one meaningful volatility regime
- Checks: signal correctness, execution realism, turnover, cost, drawdown, operational reliability

---

## Historical reference (research only — not a live promise)

ABLATION_DROP_SPY_RSI:

- Full 3x ETF weight: CAGR **146.64%**, Sharpe **1.72**, MaxDD **-49.43%**
- β≈1.5 construction (50% weight research scale): CAGR **64.81%**, Sharpe **1.72**, MaxDD **-27.36%**

---

## Commands

```bash
python3 scripts/init_paper_v1.py
python3 scripts/run_paper_day.py          # catch up from frozen_date
python3 scripts/run_paper_monthly_review.py YYYY-MM
```

---

## Forward-validation rules

1. No new historical data may be used to **modify** PAPER_V1.  
2. Daily signals append only.  
3. Monthly reviews document; they do not retune.  
4. Only SHADOW_C / Paper V1 is the formal candidate.
