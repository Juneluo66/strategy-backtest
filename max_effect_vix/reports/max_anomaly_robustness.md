# MAX anomaly robustness package

Source run: `20260810T094845Z_robustness_b305874d867e`, using a snapshot of
503 current S&P 500 constituents and Yahoo daily data from 2015-01-02. Its
data status is always `SURVIVORSHIP_BIASED_PILOT`; it is a screening result,
not evidence of historical independent alpha.

## Locked primary specification: MAX5, cap 25, 5 bp one-way cost

| Variant | Gross Sharpe | After-cost Sharpe | Cost drag (CAGR) | Realized SPY beta |
| --- | ---: | ---: | ---: | ---: |
| raw long-only | 0.727 | 0.660 | 1.09% | 0.663 |
| volatility-residualized MAX | 0.838 | 0.796 | 1.11% | 1.096 |
| beta-residualized MAX | 0.761 | 0.715 | 1.14% | 1.109 |
| SPY beta hedge | 0.143 | 0.014 | 1.25% | 0.086 |
| size neutral | BLOCKED | BLOCKED | — | — |

The `beta_neutral` row means the **MAX signal** is cross-sectionally
residualized against estimated beta. It does not make portfolio beta zero; the
separate `beta_hedged` row is the tradable SPY hedge. The free-data result does
not support a claim that either is independent Alpha.

## Cost stress for the primary raw long-only portfolio

At 0/5/10/20 bp one-way the net Sharpe is respectively 0.727 / 0.660 / 0.593 /
0.459. Annualized one-way turnover is 10.01x. These figures include modeled
turnover costs only; bid/ask, market impact and actual borrow availability
still require point-in-time execution data.

Required result order:

1. `raw`: gross and after-cost Sharpe.
2. `vol_neutral`: price-history-only volatility-residualized MAX.
3. `beta_neutral`: price-history-only beta-residualized MAX.
4. `beta_hedged`: raw MAX long leg with a separately costed SPY hedge.
5. `size_neutral`: **BLOCKED_BY_PIT_MARKET_CAP** until a QuantConnect PIT
   market-cap dataset is executed with the same frozen parameters.

The machine must not fill a size-neutral Sharpe using current shares, current
market capitalizations, or any post-formation fundamental field.
