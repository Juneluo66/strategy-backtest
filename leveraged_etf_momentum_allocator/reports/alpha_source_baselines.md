# Alpha Source Baselines

## Audit Status

- **SOURCE_VERIFICATION**: PASS
- **LOGIC_REPLICATION**: PASS
- **PERFORMANCE_RECONCILIATION**: PARTIAL
- **CLASSIFICATION**: RESEARCH_CANDIDATE

## Comparison

label     cagr   sharpe  sortino    max_dd   calmar  volatility  final_wealth  turnover  trades  incremental_vs_original
               ORIGINAL 1.988249 1.991008 3.250439 -0.494289 4.022440    0.651937  4.811139e+06 43.331080     601                      NaN
          TQQQ_BUY_HOLD 0.423989 0.886718 1.137186 -0.816598 0.519214    0.613281  1.437546e+02 12.000000       1                 1.564260
    SPY_SMA200_TQQQ_BSV 0.393861 0.953209 1.165119 -0.599177 0.657336    0.461544  1.064348e+02  9.696257     133                 1.594389
   SPY_SMA200_TQQQ_CASH 0.389516 0.946635 1.134390 -0.588914 0.661414    0.461353  1.018656e+02  4.884581      67                      NaN
 ORIGINAL_BULL_BSV_BEAR 0.752957 1.365364 1.842351 -0.599177 1.256650    0.501960  2.668940e+03 24.008735     333                      NaN
ORIGINAL_BULL_CASH_BEAR 0.747493 1.359417 1.801516 -0.588914 1.269273    0.501791  2.554363e+03 19.250247     267                      NaN
                    SPY 0.150304 0.923909 1.132961 -0.337173 0.445778    0.166668  7.153427e+00  0.000000       0                      NaN
                    QQQ 0.197075 0.972755 1.249122 -0.351187 0.561169    0.207055  1.252366e+01  0.000000       0                      NaN

## Note

incremental strategy return = ORIGINAL CAGR minus baseline CAGR (not strict alpha).
