# Public v8 comparison

| metric                     |   public_v8 |   independent_vec |   independent_evt |   difference_vs_public_evt | possible_causes                                                                                                                  |
|:---------------------------|------------:|------------------:|------------------:|---------------------------:|:---------------------------------------------------------------------------------------------------------------------------------|
| OOS total return           |       0.539 |         0.826459  |         0.65909   |                   0.12009  | Data vendor/adjustment, PIT listing proxy, partial non-OHLCV factors, cross-section, T+1 timing, cost, lots/cash, QDII exclusion |
| Maximum drawdown           |      -0.108 |        -0.33728   |        -0.287555  |                  -0.179555 | Data vendor/adjustment, PIT listing proxy, partial non-OHLCV factors, cross-section, T+1 timing, cost, lots/cash, QDII exclusion |
| Sharpe                     |       1.38  |         0.315721  |         0.244382  |                  -1.13562  | Data vendor/adjustment, PIT listing proxy, partial non-OHLCV factors, cross-section, T+1 timing, cost, lots/cash, QDII exclusion |
| Calmar                     |       7.41  |         0.0877079 |         0.0862591 |                  -7.32374  | Data vendor/adjustment, PIT listing proxy, partial non-OHLCV factors, cross-section, T+1 timing, cost, lots/cash, QDII exclusion |
| VEC minus EVT total return |      -0.019 |         0.167369  |         0.167369  |                   0.186369 | Data vendor/adjustment, PIT listing proxy, partial non-OHLCV factors, cross-section, T+1 timing, cost, lots/cash, QDII exclusion |

Public values are comparison references only. A partial factor set cannot be considered a full v8 replication.
