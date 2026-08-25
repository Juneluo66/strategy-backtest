# Low-MAX Defensive Research

Separate branch from `max_effect_vix`. Parent conclusion remains **REJECTED_AS_INDEPENDENT_ALPHA**.

This package asks whether Low-MAX is useful as a **long-only defensive** book or **high-MAX exclusion filter**, without retuning MAX or buying paid data.

## Frozen definition

From parent PURCHASE_GATE / `max_robustness_free_v1`:

- MAX5, lookback 21
- Low-MAX: decile 0.10, cap 25
- 5 bp one-way, next-open monthly rebalance
- Universe: HISTORICAL_SP500_APPROX

## Run

```bash
pip install -e ../max_effect_vix -e .
low-max-defensive research
```

Outputs under `reports/`:

- `low_max_defensive_research.md`
- `low_max_benchmarks.csv`
- `max_exclusion_grid.csv`
- `low_max_anatomy.csv`
- `low_max_regime.csv`
