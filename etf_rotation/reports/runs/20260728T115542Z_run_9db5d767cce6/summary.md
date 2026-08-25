# ETF Rotation Research Summary

This is a research-grade free-data approximation of the public v8.0 strategy, not an
exact replication and not investment advice. AkShare history, adjustment methodology,
non-OHLCV coverage, QDII timing, and fill assumptions can differ materially from QMT
production data. Public backtest and short live figures are comparison references only.
Parameters are frozen before the 2025-05-01 out-of-sample window; do not retune on OOS.


## Variant results

| variant          | engine   |   total_return |   annual_return |   annual_volatility |    sharpe |    sortino |   max_drawdown |     calmar |   win_rate |   profit_factor |   trades |
|:-----------------|:---------|---------------:|----------------:|--------------------:|----------:|-----------:|---------------:|-----------:|-----------:|----------------:|---------:|
| M1_VEC           | VEC      |      1.85431   |      0.0520699  |           0.248974  | 0.209138  | 0.205659   |      -0.608584 | 0.0855591  |   0.354331 |         1.08169 |     1099 |
| M1_EVT           | EVT      |      3.88582   |      0.0797969  |           0.473768  | 0.16843   | 0.31649    |      -0.539389 | 0.147939   |   0.354523 |         1.17625 |     1119 |
| H1_VEC           | VEC      |      0.17936   |      0.00801599 |           0.236958  | 0.0338287 | 0.0330748  |      -0.723809 | 0.0110747  |   0.349337 |         1.03668 |      589 |
| H1_EVT           | EVT      |      1.68647   |      0.0489889  |           0.496561  | 0.0986564 | 0.198587   |      -0.499291 | 0.0981169  |   0.347417 |         1.16116 |      609 |
| R1_VEC           | VEC      |      0.0213647 |      0.00102361 |           0.117189  | 0.0087347 | 0.00813859 |      -0.576508 | 0.00177553 |   0.349337 |         1.01946 |      589 |
| R1_EVT           | EVT      |      0.30674   |      0.0130319  |           0.1171    | 0.111289  | 0.118211   |      -0.365392 | 0.0356656  |   0.347609 |         1.05311 |      609 |
| v8_reference_VEC | VEC      |      0.826459  |      0.0295821  |           0.0936968 | 0.315721  | 0.23332    |      -0.33728  | 0.0877079  |   0.349914 |         1.14105 |      495 |
| v8_reference_EVT | EVT      |      0.65909   |      0.0248042  |           0.101498  | 0.244382  | 0.201019   |      -0.287555 | 0.0862591  |   0.354331 |         1.15067 |      500 |

## VEC−EVT gap

| variant          |   vec_minus_evt_total_return |
|:-----------------|-----------------------------:|
| H1_EVT           |                          nan |
| H1_VEC           |                          nan |
| M1_EVT           |                          nan |
| M1_VEC           |                          nan |
| R1_EVT           |                          nan |
| R1_VEC           |                          nan |
| v8_reference_EVT |                          nan |
| v8_reference_VEC |                          nan |

A gap above 5 percentage points is a release blocker requiring signal, execution, or cost audit.
