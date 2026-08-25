# Mechanism — Macro Correlates, VIF, Partial R²

## Judgment: `MIXED_MECHANISM`

Sample: `2014-11-05` → `2026-08-21`
Suppressor/collinearity note: `BTC_TSTAT_RISES_AFTER_CONTROLS__CHECK_SUPPRESSOR_OR_COLLINEARITY`

## Why does BTC t-stat rise after VIX + trends?

- Univariate β/t: `0.01018` / `1.97`
- After QQQ+SPY trend + VIX β/t: `0.01561` / `3.07`

If |t| rises while VIF is moderate, BTC may act as a **suppressor** (sharing noise with VIX/trend) or carry residual orthogonal regime info. Partial R² decides economic relevance.

## VIF

- `btc_signal`: `1.08`
- `qqq_trend`: `2.33`
- `spy_trend`: `2.43`
- `vix_z`: `1.26`
- `dxy_z`: `1.02`

## Partial R² (k=20) of BTC signal

- Forward **return**: partial R²=`0.020723934342475523` (ΔR²=`0.01956804152078162`, full R²=`0.07534378383843354`)
- Forward **RV**: partial R²=`0.008748846320387716` (ΔR²=`0.005671471630422142`)

**t≈3 can coexist with partial R² ≪ 1%** — statistically detectable, economically thin for return forecasting.

## Nested return regressions

| Spec | β_BTC | t | R² |
|---|---:|---:|---:|
| univ | 0.01018 | 1.97 | 0.0090 |
| plus_qqq | 0.01315 | 2.59 | 0.0221 |
| plus_trends | 0.01360 | 2.63 | 0.0233 |
| plus_vix | 0.01561 | 3.07 | 0.0753 |
| plus_dxy | 0.01573 | 3.09 | 0.0774 |

## Corr(BTC signal, macro)

| Macro | corr | n |
|---|---:|---:|
| vix_z | -0.183 | 2965 |
| dxy_z | -0.014 | 2965 |

FRED fetch errors:

- `HY_OAS`: `The read operation timed out`
- `REAL_YIELD_10Y`: `The read operation timed out`
- `BROAD_DOLLAR`: `The read operation timed out`
- `NFCI`: `The read operation timed out`

## Rolling 2y BTC β (on return k=20, controlled)

- Median β: `0.01757525499632689`
- % windows t>2: `0.18803418803418803`
- % windows t<0: `0.2905982905982906`
- Mean incremental OOS R²: `0.0020175191977924952`

## Bottom line

Mechanism work can upgrade an empirical gate only if incremental OOS R² / partial R² is material on **risk or return**. Significant HAC t alone is not enough.
