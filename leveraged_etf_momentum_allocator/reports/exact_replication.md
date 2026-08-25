# Exact Replication

## Source

QuantConnect ConditionalSectorRotation — frozen in configs/original.yaml

## Dates

- Requested start: 2012-01-01
- Effective start: 2012-07-20
- End: 2026-08-21
- First signal: 2012-07-20
- First trade: 2012-07-20
- ETF inceptions: {'SPY': '2010-01-04', 'QQQ': '2010-01-04', 'TQQQ': '2010-02-11', 'UVXY': '2011-10-04', 'TECL': '2010-01-04', 'SPXL': '2010-01-04', 'SQQQ': '2010-02-11', 'TECS': '2010-01-04', 'BSV': '2010-01-04'}

## Execution Semantics (QC)

- signal_timestamp: t close (OnData daily bar complete)
- indicator_timestamp: t close (Current.Value includes bar t)
- order_timestamp: t close (SetHoldings in OnData)
- fill_timestamp: t close (daily backtest fill at bar close)
- return_attribution: Day t return on prior holding; switch at t close for t+1
- lookahead_note: Same-bar signal+fill at close — matches QC daily replication

## QC Performance

| Metric | Value |
|--------|-------|
| CAGR (net) | 198.82% |
| Sharpe (rf=0) | 1.99 |
| Sortino (rf=0) | 3.25 |
| Max Drawdown | -49.43% |
| Calmar | 4.02 |
| Final Wealth | 4811139.50 |
| Annual Turnover | 43.33 |

## Next-Open Performance

| Metric | Value |
|--------|-------|
| CAGR (net) | 200.15% |
| Sharpe (rf=0) | 2.02 |
| Sortino (rf=0) | 3.22 |
| Max Drawdown | -47.95% |
| Calmar | 4.17 |
| Final Wealth | 5120679.84 |
| Annual Turnover | 43.35 |

## Execution Delta

CAGR QC: 198.82% vs Next-Open: 200.15% (diff -1.3pp)

## Decision Stats

- Decisions: 3542
- Target changes: 301
- Actual trades: 601

## Time in Target

target  days  pct_time
  TQQQ  2911  0.821852
  TECL   211  0.059571
  TECS   166  0.046866
  UVXY   129  0.036420
   BSV   114  0.032185
  SPXL    11  0.003106

## Holding Attribution

ticker  days_held  portfolio_time_pct  number_of_entries  total_pnl_proxy  cagr_contribution_approx  average_daily_return  average_trade_return  median_trade_return  win_rate_daily  win_rate_trades  worst_trade  best_trade
  TQQQ       2911            0.821852                 84        11.338850                  1.305205              0.003895              0.086034             0.034666        0.569220         0.650602    -0.318706    0.909212
  TECS        166            0.046866                 54         2.890164                 46.690386              0.017411              0.030286             0.002378        0.572289         0.500000    -0.133943    0.262913
  UVXY        129            0.036420                 56         2.223309                 55.253541              0.017235              0.095789             0.045341        0.689922         0.750000    -0.087878    0.607417
  TECL        211            0.059571                 66         1.604278                  2.836914              0.007603              0.063726             0.060328        0.530806         0.833333    -0.160434    0.355145
   BSV        114            0.032185                 34         0.138066                 -0.074239              0.001211              0.001874             0.001126        0.570175         0.705882    -0.003844    0.010278
  SPXL         11            0.003106                  7         0.049605                  1.454324              0.004510              0.057697             0.035855        0.636364         0.857143    -0.096116    0.278063

## Branch Attribution (top 10)

branch terminal_target  days  pct_time  cagr_contribution_approx  pnl_contribution  avg_daily_return  win_rate  volatility
                                                                               SPY > SPY_SMA200 → QQQ_RSI <= 81 → SPY_RSI <= 80            TQQQ  2911  0.821852              1.305205e+00         11.338850          0.003895  0.569220    0.545528
             SPY <= SPY_SMA200 → TQQQ_RSI >= 30 → SPY_RSI >= 30 → UVXY_RSI <= 74 → TQQQ <= TQQQ_SMA20 → MAX_RSI(TECS,BSV)->TECS            TECS   131  0.036985              1.696057e+01          1.735775          0.013250  0.549618    0.942809
                       SPY <= SPY_SMA200 → TQQQ_RSI >= 30 → SPY_RSI >= 30 → UVXY_RSI <= 74 → TQQQ > TQQQ_SMA20 → SQQQ_RSI >= 34            TECL   139  0.039243              3.546175e+00          0.944088          0.006792  0.553957    0.627589
                                            SPY <= SPY_SMA200 → TQQQ_RSI >= 30 → SPY_RSI >= 30 → UVXY_RSI > 74 → UVXY_RSI <= 84            UVXY     9  0.002541              2.020723e+09          0.875896          0.097322  0.666667    2.314567
                                                                                                SPY > SPY_SMA200 → QQQ_RSI > 81            UVXY    77  0.021739              1.286122e+01          0.835845          0.010855  0.688312    0.432608
                                                                                              SPY <= SPY_SMA200 → TQQQ_RSI < 30            TECL    72  0.020327              1.765474e+00          0.660190          0.009169  0.486111    1.749506
                        SPY <= SPY_SMA200 → TQQQ_RSI >= 30 → SPY_RSI >= 30 → UVXY_RSI <= 74 → TQQQ > TQQQ_SMA20 → SQQQ_RSI < 34            TECS    33  0.009317              6.444978e+01          0.590204          0.017885  0.636364    0.783879
SPY <= SPY_SMA200 → TQQQ_RSI >= 30 → SPY_RSI >= 30 → UVXY_RSI > 74 → UVXY_RSI > 84 → QQQ <= QQQ_SMA20 → MAX_RSI(TECS,BSV)->TECS            TECS     2  0.000565              1.546373e+27          0.564185          0.282093  1.000000    0.310624
                                                                                SPY > SPY_SMA200 → QQQ_RSI <= 81 → SPY_RSI > 80            UVXY    43  0.012140              1.712024e+01          0.511568          0.011897  0.697674    0.415515
              SPY <= SPY_SMA200 → TQQQ_RSI >= 30 → SPY_RSI >= 30 → UVXY_RSI <= 74 → TQQQ <= TQQQ_SMA20 → MAX_RSI(TECS,BSV)->BSV             BSV   114  0.032185             -7.423856e-02          0.138066          0.001211  0.570175    0.929837

## UVXY Branch

- uvxy_entry_signals: 129
- uvxy_days_held: 129
- pct_portfolio_time: 0.036420101637492944
- median_holding_days: 3.0
- avg_holding_days: 3.6964285714285716
- total_pnl_proxy: 2.2233090583267225
- avg_daily_return_in_uvxy: 0.017234953940517227
- win_rate_in_uvxy: 0.689922480620155

## SQQQ Note

SQQQ is signal-only; never a SetHoldings target in source code.
