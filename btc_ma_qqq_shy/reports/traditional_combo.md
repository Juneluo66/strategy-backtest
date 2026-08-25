# Frozen Traditional Comparator: QQQ Trend + VIX

Rule id: **`QQQ200_VIX20_v1`** — QQQ > SMA200 AND VIX < 20 at prior session → QQQ else SHY
Logic: `all_required` | VIX threshold: `20.0` | QQQ SMA: `200`
Judgment: **`BTC_BEATS_FROZEN_TRADITIONAL_COMBO`**

Discovery vol-matched w_QQQ (frozen at cutoff): `0.56`
BTC vs combo weekly signal agreement: `54.3%`

## Full sample (`2014-11-05` → `2026-08-21`)

| Portfolio | CAGR | Sharpe | Vol | MaxDD | w_QQQ |
|---|---:|---:|---:|---:|---:|
| BTC_timing | 17.27% | 1.361 | 12.29% | -16.24% | 0.47 |
| QQQ_200DMA_only | 16.53% | 1.004 | 16.69% | -25.18% | 0.82 |
| VIX_lt_20_only | 5.51% | 0.461 | 13.78% | -28.31% | 0.70 |
| QQQ200DMA_VIX20_combo | 5.64% | 0.488 | 13.07% | -23.73% | 0.66 |
| vol_matched_static | 11.58% | 0.960 | 12.23% | -22.43% | 0.56 |

BTC vs combo: ΔCAGR `11.63` pp, ΔSharpe `0.873`, ΔMaxDD `7.49` pp

## Discovery only (pre-OOS cutoff)

| Portfolio | CAGR | Sharpe | Vol | MaxDD | w_QQQ |
|---|---:|---:|---:|---:|---:|
| BTC_timing | 17.32% | 1.363 | 12.31% | -16.24% | 0.47 |
| QQQ_200DMA_only | 16.72% | 1.014 | 16.71% | -25.18% | 0.82 |
| VIX_lt_20_only | 5.65% | 0.470 | 13.79% | -28.31% | 0.70 |
| QQQ200DMA_VIX20_combo | 5.78% | 0.498 | 13.08% | -23.73% | 0.66 |
| vol_matched_static | 11.68% | 0.967 | 12.24% | -22.43% | 0.56 |

Combo encodes trend + vol regime without BTC. If BTC ≈ combo, BTC may be a bundled traditional filter; if BTC >> combo on risk-adj, BTC adds orthogonal timing.
