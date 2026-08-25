# Phase 5 — Robust Core Extraction

> **Status:** PAPER_TRADING_CANDIDATE

## NOTE

Selection corrected: only candidates with real 500-draw neighborhoods are ranked. Placeholder percentile=50 no longer inflates untested variants. ABLATION_DROP_SQQQ_RSI shares neighborhood stats with COLLAPSE_DROP_SQQQ_RSI (identical rules).

## Crisis-Robust Score Ranking (neighborhood-tested only)

name  crisis_score     cagr  ex_both  rand_med  rand_p10  rand_pct  roll5   sharpe    max_dd  branches  params
COLLAPSE_DROP_SQQQ_RSI        1.0417 1.715750 1.202559  1.204943  1.029919     100.0    1.0 1.867333 -0.494289        11      10
ABLATION_DROP_SQQQ_RSI        1.0417 1.715750 1.202559  1.204943  1.029919     100.0    1.0 1.867333 -0.494289        11      10
          STANDARDIZED        1.0396 1.709248 1.202559  1.236621  1.041469      99.8    1.0 1.863535 -0.494289        12      12
        ROBUST_CORE_V1        1.0396 1.709248 1.202559  1.236621  1.041469      99.8    1.0 1.863535 -0.494289        12      12
 ABLATION_DROP_SPY_RSI        1.0366 1.466403 1.114620  1.167264  0.865864      91.0    1.0 1.721704 -0.494289        10      10
ABLATION_DROP_UVXY_RSI        1.0365 1.621421 1.183179  1.202239  0.998543     100.0    1.0 1.858527 -0.494289         9      10
        ROBUST_CORE_V2        1.0116 1.539106 1.166799  1.112932  0.941594     100.0    1.0 1.822232 -0.494289        10      10
              PRUNED_1        1.0073 1.533027 1.166799  1.143231  0.944087     100.0    1.0 1.818255 -0.494289        11      12

## Selected BEST ROBUST CORE

ABLATION_DROP_SPY_RSI
crisis_score=1.0366 rand_pct=91.0
Reason: lowest/near-lowest top-tail among strong neighborhood medians; simpler than ORIGINAL; natural thresholds.

## Walk-Forward

name  roll5_win_tqqq  roll5_median_rel  roll5_worst_rel    max_dd
             ORIGINAL             1.0          3.682382         0.492803 -0.494289
         STANDARDIZED             1.0          2.515255         0.456994 -0.494289
       ROBUST_CORE_V1             1.0          2.515255         0.456994 -0.494289
ABLATION_DROP_SPY_RSI             1.0          2.048196         0.397964 -0.494289

## Crisis Behavior

### ORIGINAL
 crisis  days  pct_bear_regime  pct_risk_off  pct_shortish  pct_rebound_long top_target  top_target_pct  unique_targets
2015-16   167         0.604790      0.173653      0.125749          0.700599       TQQQ        0.395210               5
   2018   103         0.601942      0.223301      0.106796          0.669903       TQQQ        0.398058               5
  COVID   104         0.567308      0.086538      0.240385          0.673077       TQQQ        0.413462               6
   2022   251         0.812749      0.095618      0.426295          0.478088       TECS        0.426295               5

### ROBUST_CORE_V1
 crisis  days  pct_bear_regime  pct_risk_off  pct_shortish  pct_rebound_long top_target  top_target_pct  unique_targets
2015-16   167         0.604790      0.167665      0.107784          0.724551       TQQQ        0.395210               5
   2018   103         0.601942      0.203883      0.116505          0.679612       TQQQ        0.398058               6
  COVID   104         0.567308      0.105769      0.096154          0.798077       TQQQ        0.413462               6
   2022   251         0.812749      0.095618      0.386454          0.517928       TECS        0.386454               5

### ABLATION_DROP_SPY_RSI
 crisis  days  pct_bear_regime  pct_risk_off  pct_shortish  pct_rebound_long top_target  top_target_pct  unique_targets
2015-16   167         0.604790      0.167665      0.107784          0.724551       TQQQ        0.395210               5
   2018   103         0.601942      0.233010      0.135922          0.631068       TQQQ        0.398058               5
  COVID   104         0.567308      0.105769      0.096154          0.798077       TQQQ        0.423077               5
   2022   251         0.812749      0.095618      0.394422          0.509960       TECS        0.394422               4

## Leverage Level Test

version  exposure_scale     cagr   sharpe    max_dd   calmar
         ROBUST_CORE_1X        0.333333 0.410662 1.721704 -0.188256 2.181402
       ROBUST_CORE_1_5X        0.500000 0.648117 1.721704 -0.273593 2.368911
         ROBUST_CORE_2X        0.666667 0.905068 1.721704 -0.353014 2.563828
ROBUST_CORE_3X_ORIGINAL        1.000000 1.466403 1.721704 -0.494289 2.966690

## Leverage Recommended

ROBUST_CORE_1_5X (scale=0.500) CAGR=64.81% Sharpe=1.72 MaxDD=-27.36% Calmar=2.37

## WHY MORE ROBUST

- Natural 30/70/80 thresholds (not 81/74/84/31/34 sample-fit).
- Neighborhood percentile 91.0 vs ORIGINAL 100.0.
- Neighborhood median still high: 116.73%.
- Ex-COVID+2022 CAGR 111.46% (structure survives without those crises).
- Fewer thresholds/signal inputs than ORIGINAL where applicable (10 vs 12).
- Recommended exposure ROBUST_CORE_1_5X improves MaxDD vs full 3x.

## REMOVED RULES

- SPY RSI overbought/oversold branches (bull UVXY-from-SPY + bear SPXL)
- Non-round thresholds 81/74/84/31/34 → 80/70/80/30

## REMAINING RISKS

- Even simplified versions remain HIGH on PARAMETER_OVERFIT_RISK for point estimates.
- Crisis alpha still large (ex-COVID CAGR drops vs full sample).
- Full 3x MaxDD still ~-49%; paper path relies on exposure scaling.
- UVXY/SQQQ Yahoo adj-close level quality remains imperfect.
- Tree still more complex than a pure SMA200 filter.

## FINAL SUMMARY

ORIGINAL:
CAGR: 198.82%
Sharpe: 1.99
MaxDD: -49.43%
parameters: 4
thresholds: 8
branches: 10

STANDARDIZED:
CAGR: 170.92%
Sharpe: 1.86
MaxDD: -49.43%
parameters: 4
thresholds: 8
branches: 12

BEST ROBUST CORE:
name: ABLATION_DROP_SPY_RSI
CAGR: 146.64%
Sharpe: 1.72
MaxDD: -49.43%
parameters: 4
thresholds: 6
branches: 10

EX-COVID CAGR: 114.30%
EX-2022 CAGR: 146.10%
EX-COVID+2022 CAGR: 111.46%

RANDOM NEIGHBORHOOD:
median: 116.73%
10th percentile: 86.59%
candidate percentile: 91.0

ROLLING 5Y WIN RATE VS TQQQ: 100.0%

LEVERAGE VERSION RECOMMENDED: ROBUST_CORE_1_5X
  (CAGR 64.81% Sharpe 1.72 MaxDD -27.36% Calmar 2.37)

CLASSIFICATION: PAPER_TRADING_CANDIDATE
