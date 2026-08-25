# Timing Advantage Attribution

Return basis: **yahoo_adj_close_total_return**
Sample: `2014-11-10` → `2026-08-21`
Vol-matched static w_QQQ = `0.56`
CAGR edge (BTC timing − vol-matched): **`5.71` pp**
Narrative: **`MIXED_OR_OFFENSE_LED`**

## A / B decomposition (vs vol-matched static)

| Bucket | Meaning | Cum wealth (daily piece) | CAGR piece | Σ daily active | % of Σ active |
|---|---|---:|---:|---:|---:|
| **A Risk-on** | BTC→QQQ; static only `56%` QQQ | 2.1539 | 6.73% | 78.45% | 133.2% |
| **B Risk-off** | BTC→SHY; static still `56%` QQQ | 0.7736 | -2.16% | -19.54% | -33.2% |
| **Total** | | 1.6662 | 4.43% | 58.91% | 100% |

A and B are mutually exclusive daily pieces; product of (1+A) and (1+B) over their days equals total active wealth.

## Regime splits

| Regime | n days | A Σ active | B Σ active | B share |
|---|---:|---:|---:|---:|
| Bull (QQQ>200DMA) | 2256 | 72.93% | -57.61% | -376.1% |
| Bear (QQQ≤200DMA) | 705 | 5.52% | 38.07% | 87.3% |
| High VIX | 1480 | 7.25% | 58.38% | 89.0% |
| Low VIX | 1481 | 71.20% | -77.92% | 1159.7% |

## Yearly active (strategy − vol-matched)

| Year | QQQ | Strat | Static | Active A | Active B | B share |
|---:|---:|---:|---:|---:|---:|---:|
| 2014 | 1.6% | 2.1% | 0.9% | 0.99% | 0.21% | 18% |
| 2015 | 9.4% | 11.0% | 5.8% | 4.61% | 0.17% | 3% |
| 2016 | 7.1% | 4.1% | 4.6% | 1.76% | -1.87% | 1607% |
| 2017 | 32.7% | 27.2% | 17.4% | 10.65% | -2.43% | -30% |
| 2018 | -0.1% | 4.9% | 1.2% | 1.57% | 1.42% | 48% |
| 2019 | 39.0% | 21.7% | 22.4% | 7.48% | -7.79% | 2534% |
| 2020 | 48.4% | 34.5% | 28.5% | 12.44% | -8.20% | -193% |
| 2021 | 27.4% | 18.0% | 14.6% | 8.03% | -4.69% | -140% |
| 2022 | -32.6% | -2.4% | -20.2% | 1.09% | 18.37% | 94% |
| 2023 | 54.9% | 40.6% | 30.6% | 13.57% | -5.81% | -75% |
| 2024 | 25.6% | 7.7% | 16.0% | 1.93% | -9.05% | 127% |
| 2025 | 20.8% | 25.1% | 14.3% | 7.99% | 0.78% | 9% |
| 2026 | 16.4% | 16.2% | 9.8% | 6.34% | -0.66% | -12% |

## Frozen benchmark: QQQ 200DMA → QQQ else SHY

Rule: `QQQ > SMA200 at prior session → QQQ else SHY; weekly QC week-start` — **not tuned** on this sample.
Judgment: **`BTC_BEATS_FROZEN_QQQ_200DMA_BENCHMARK`**

| Portfolio | CAGR | Sharpe | Vol | MaxDD | w_QQQ |
|---|---:|---:|---:|---:|---:|
| BTC_timing_QC_adj_0bps | 17.29% | 1.362 | 12.29% | -16.24% | 0.47 |
| vol_matched_static | 11.56% | 0.959 | 12.23% | -22.43% | 0.56 |
| QQQ_200DMA_SHY_adj_0bps | 1.57% | 1.044 | 1.50% | -5.71% | 0.00 |
| 100pct_QQQ | 18.82% | 0.902 | 21.86% | -35.12% | 1.00 |

BTC vs QQQ200DMA: ΔCAGR `15.72` pp, ΔSharpe `0.318`, ΔMaxDD `-10.53` pp
