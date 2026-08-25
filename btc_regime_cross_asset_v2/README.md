# BTC Regime Cross-Asset v2 (Research)

**Independent research branch.** Does not modify `btc_ma_qqq_shy` (v1 production / frozen OOS).

## Questions

- **Q1:** Does the same BTC SMA50+MOM20 gate transfer across risk-sensitive ETFs (QQQ, SMH, SOXX, IWO, IWM, SPY)?
- **Q2:** Is SHY the right risk-off sleeve vs BIL, IEF, TLT, GLD?
- **Tiny OFF rule:** BTC OFF → IEF if IEF>SMA200 else SHY (train-selected, test-locked).

## Frozen BTC gate (unchanged from v1)

- Bitfinex BTC, SMA50 + MOM20, QC week-start proxy
- Parameters are **not** tuned in v2

## Splits (pre-registered)

| Phase | Dates |
|--------|--------|
| Train | 2014-11-05 → 2020-12-31 |
| Test | 2021-01-01 → 2026-08-06 |

Test end is **before** v1 OOS cutoff (2026-08-07). v1 ledger remains the only true forward OOS.

## Matrix (30 combos)

6 risk-on × 5 risk-off, each vs buy-hold ON and vol-matched static (train-calibrated on test).

## Walk-forward blocks

- 2014–2018 train → 2019–2020 test
- 2014–2020 train → 2021–2022 test
- 2014–2022 train → 2023–2024 test
- 2014–2024 train → 2025–2026 test

## Setup

```bash
cd strategy-backtest/btc_regime_cross_asset_v2
python3 -m pip install -e .
btc-regime-v2 fetch
btc-regime-v2 full-audit
```

Reports under `reports/`:

- `matrix_train.md`, `matrix_test.md`
- `walkforward.md`
- `off_rules.md`

## v1 vs v2

| Track | Path | Role |
|--------|------|------|
| v1 production | `btc_ma_qqq_shy` | Frozen OOS ledger, no retuning |
| v2 research | `btc_regime_cross_asset_v2` | Train/test, walk-forward, matrix |

Even if v2 finds e.g. SMH/IEF Sharpe 1.6, it **does not** replace v1 OOS evidence.
