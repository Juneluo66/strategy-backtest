# Public v8 comparison

| metric                     |   public_v8 |   independent_vec |   independent_evt |   difference_vs_public_evt | possible_causes                                                                                                                  |
|:---------------------------|------------:|------------------:|------------------:|---------------------------:|:---------------------------------------------------------------------------------------------------------------------------------|
| OOS total return           |       0.539 |        -0.0894337 |        -0.127826  |                 -0.666826  | Data vendor/adjustment, PIT listing proxy, partial non-OHLCV factors, cross-section, T+1 timing, cost, lots/cash, QDII exclusion |
| Maximum drawdown           |      -0.108 |        -0.254651  |        -0.247339  |                 -0.139339  | Data vendor/adjustment, PIT listing proxy, partial non-OHLCV factors, cross-section, T+1 timing, cost, lots/cash, QDII exclusion |
| Sharpe                     |       1.38  |        -0.27761   |        -0.42175   |                 -1.80175   | Data vendor/adjustment, PIT listing proxy, partial non-OHLCV factors, cross-section, T+1 timing, cost, lots/cash, QDII exclusion |
| Calmar                     |       7.41  |        -0.297196  |        -0.438792  |                 -7.84879   | Data vendor/adjustment, PIT listing proxy, partial non-OHLCV factors, cross-section, T+1 timing, cost, lots/cash, QDII exclusion |
| VEC minus EVT total return |      -0.019 |         0.0383922 |         0.0383922 |                  0.0573922 | Data vendor/adjustment, PIT listing proxy, partial non-OHLCV factors, cross-section, T+1 timing, cost, lots/cash, QDII exclusion |

Public values are comparison references only. A partial factor set cannot be considered a full v8 replication.
