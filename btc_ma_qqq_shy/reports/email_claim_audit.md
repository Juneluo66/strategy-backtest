# BTC MA / Momentum → QQQ / SHY — Email Claim Audit

## Scope

- Requested from: `2014-01-01` (email 'since 2014')
- Effective window: `2014-11-05` → `2026-08-21` (BTC Yahoo start `2014-09-17`, first SMA/mom signal `2014-11-05`)
- Classification: `EMAIL_CLAIM_AUDIT_DISCOVERY_ONLY`
- Judgment: **`EMAIL_CLAIM_SUPPORTED_ON_THIS_SAMPLE`**
- Switches (audit): `130`
- Occupancy QQQ/SHY: `47.35%` / `52.65%`

## Rules (frozen)

- Weekly last trading session: if BTC-USD > 50DMA **and** 20-day momentum > 0 → hold **QQQ**, else **SHY**.
- Position applies from the **next** session (no same-bar fill).
- Benchmarks: SPY, QQQ. Email claim: since 2014, better drawdown & risk-adjusted returns vs both.

## Absolute performance (audit window)

| Series | CAGR | Vol | Sharpe | Sortino | Calmar | Max DD | Final NAV |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 15.03% | 12.11% | 1.220 | 1.934 | 0.926 | -16.24% | 5.212 |
| SPY | 13.80% | 17.52% | 0.829 | 1.293 | 0.409 | -33.72% | 4.588 |
| QQQ | 18.86% | 21.85% | 0.903 | 1.441 | 0.537 | -35.12% | 7.666 |
| SHY | 1.56% | 1.50% | 1.042 | 1.836 | 0.274 | -5.71% | 1.201 |

## Relative (Metric C style nav_s/nav_b)

- **vs_SPY**: rel CAGR `1.09%`, final rel `1.136`, rel maxDD `-35.10%`, IR `0.015`
- **vs_QQQ**: rel CAGR `-3.22%`, final rel `0.680`, rel maxDD `-50.30%`, IR `-0.271`

## Email claim checks

- Max DD better than SPY: `True`
- Max DD better than QQQ: `True`
- Sharpe better than SPY: `True`
- Sharpe better than QQQ: `True`
- Sortino better than SPY/QQQ: `True` / `True`
- Calmar better than SPY/QQQ: `True` / `True`
- **Claim (DD + Sharpe vs both): `True`**

## Notes

- DISCOVERY_SAMPLE / EMAIL_CLAIM_AUDIT — not pre-registered OOS.
- Signal: BTC-USD > SMA50 and 20d return > 0; weekly last-session check.
- Execution: next session after week-end decision (no same-bar fill).
- Yahoo BTC-USD history begins ~2014-09-17; SMA50 delays first usable signal.
- Costs: 0 bps in base case (see frozen.yaml).
- No IBKR / production / other-strategy changes.
