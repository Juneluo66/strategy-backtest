# PURCHASE_GATE — Sharadar one-month decision

## Status

- DATA_TIER: `HISTORICAL_SP500_APPROX`
- SURVIVORSHIP_BIAS: `REDUCED_NOT_ELIMINATED`
- PIT_VALIDATED: `False`
- SIZE_NEUTRAL: `BLOCKED_BY_PIT_MARKET_CAP`

Frozen parameters (no retuning): MAX5 / lookback 21 / decile 0.1 / cap 25 / 5.0 bp one-way.

## 1. FF3 full regression (long low-MAX, after costs)

- N months: 138
- alpha (monthly): -0.002075 (t=-1.003)
- alpha (ann.): -0.0249
- MKT_RF: 0.7295 (t=15.613)
- SMB: -0.1805 (t=-2.317)  ← size-confound check
- HML: 0.2514 (t=4.571)

## 2. Frozen-parameter subperiods

| Period | Gross Sharpe | Net Sharpe | Mean IC | Max DD (net) | Ann. turnover |
|---|---:|---:|---:|---:|---:|
| P1_2015_2018 | 0.727 | 0.644 | -0.0147 | -0.170 | 10.11 |
| P2_2019_2022 | 0.824 | 0.774 | 0.0104 | -0.331 | 9.74 |
| P3_2023_2026 | 0.399 | 0.318 | 0.0391 | -0.188 | 10.34 |

## 3. Long low-MAX vs short high-MAX legs

| Leg | Gross CAGR | Net CAGR | Gross Sharpe | Net Sharpe | Market beta |
|---|---:|---:|---:|---:|---:|
| long_low_MAX | 0.0928 | 0.0821 | 0.665 | 0.599 | 0.667 |
| short_high_MAX | -0.2724 | -0.2667 | -0.888 | -0.863 | -1.399 |

Long+short (low long + high short) net Sharpe: **-0.663**

Primary return driver: `long_low_MAX`

Note: `short_high_MAX` is the economic short of the high-MAX long book (−returns).

## 4. Supporting evidence

- Full-sample after-cost long-only Sharpe is 0.599 (>0.3).
- All three frozen subperiods have positive net Sharpe: [0.644, 0.774, 0.318].
- FF3: alpha=-0.0021 (t=-1.00), MKT=0.729 (t=15.61), SMB=-0.180 (t=-2.32), HML=0.251 (t=4.57).
- SMB loading is negative and significant (-0.180, t=-2.32); not a small-cap bet.
- Long low-MAX net Sharpe is 0.599.
- Leg attribution (net CAGR): long_low_MAX=0.0821, short_high_MAX=-0.2667; primary driver=long_low_MAX.

## 5. Opposing evidence

- Cross-sectional IC is not consistently negative across subperiods: [-0.014680636345339636, 0.010360456879746155, 0.03909055631430909].
- FF3 alpha is not significantly positive (alpha=-0.00207549006116614, t=-1.0026679447370936).
- Short high-MAX net Sharpe is negative (-0.863); short leg does not contribute positively.
- Combined long+short net Sharpe is weak (-0.6630359295297512).
- Return is long-leg dominated (long net CAGR 0.0821 vs short -0.2667); classic MAX short-lottery story is weak on this sample.
- DATA_TIER=HISTORICAL_SP500_APPROX; SURVIVORSHIP_BIAS=REDUCED_NOT_ELIMINATED (reduced, not eliminated).
- PIT_VALIDATED=false; size neutralization remains BLOCKED_BY_PIT_MARKET_CAP.
- DELISTING_RETURN=UNAVAILABLE on Yahoo / index-exit proxy.
- Do not purchase merely because free Sharpe is high.

## 6. Decision

**NO — free after-cost Sharpe is positive, but FF3 alpha is not significantly positive. Buying Sharadar would mainly re-price a factor/risk story, not settle an unresolved independent-alpha claim. Do not purchase on this evidence.**

Rule used: do not buy because Sharpe is high; buy only if free evidence leaves PIT/size/delisting
as the binding uncertainty and the pattern is otherwise coherent under frozen parameters.
