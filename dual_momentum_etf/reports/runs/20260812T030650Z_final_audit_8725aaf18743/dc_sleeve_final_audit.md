# D+C Sleeve Final Audit (pre-IBKR)

- Frozen D+C: `attribution_DC` — **3/6/12 + category constraint unchanged**
- Default paper candidate: **80% SPY + 20% D+C**
- Conservative shadow only: **60% SPY + 40% D+C** (no weight search)
- Sample: `2005-03-01` → `2026-08-10`
- config_hash: `8725aaf1874386e68016e9e7ad290f09b8528a34ecf7857f350acfa8a208b1c2`
- Audit gate: **PASS**

## 1. Relative NAV underwater (Metric C only)

| Portfolio | Longest underwater | Start | Trough | Recovery | Ongoing? | Current rel DD | Max rel DD | 3y win | 5y win | 10y win |
|---|---:|---|---|---|---|---:|---:|---:|---:|---:|
| 80_20 | 210m | 2009-03-10 | 2024-12-24 | NONE | yes | -19.20% | -21.83% | 25.68% | 21.72% | 22.46% |
| 60_40 | 210m | 2009-03-10 | 2024-12-24 | NONE | yes | -35.41% | -39.45% | 25.68% | 21.72% | 21.74% |
| 100_dc | 210m | 2009-03-10 | 2024-12-24 | NONE | yes | -69.04% | -73.37% | 23.42% | 19.70% | 20.29% |
| 80_20_ief | 210m | 2009-03-10 | 2026-08-10 | NONE | yes | -35.28% | -35.28% | 19.82% | 20.71% | 8.70% |
| 80_20_cash | 210m | 2009-03-10 | 2026-08-07 | NONE | yes | -37.74% | -37.75% | 15.32% | 12.63% | 0.00% |
| 80_20_gld | 181m | 2011-08-23 | 2022-01-03 | NONE | yes | -21.28% | -27.48% | 45.50% | 31.82% | 26.81% |
| 90_10_ief | 210m | 2009-03-10 | 2026-08-10 | NONE | yes | -19.37% | -19.37% | 19.82% | 20.71% | 10.87% |
- These are **relative-NAV opportunity-cost intervals**, not consecutive single-month underperformance streaks.

## 2. Construction audit

- Outer monthly target rebalance: `True`
- Weights drift between rebalances (not constant 0.8/0.2 daily): `True`
- Signal = month-end close; execution = next session: `True` / `True`
- No same-close fill after signal: `True`
- D+C internal costs inside D+C NAV: `True`
- Outer costs only on sleeve rebalance: `True`
- Total-return basis: `Yahoo Adj Close / strategy equity_net`
- Example rebalance: `{"signal_date": "2005-03-31", "execution_date": "2005-04-01", "execution_rule": "next_session_after_month_end_close_signal", "price_basis": "leg daily total-return units; fill modeled at session open via full-day return after reset", "turnover_l1": 0.0059405989567968, "outer_cost": 2.9702994783984e-06, "weights_before": {"spy": 0.7970297005216016, "dc": 0.20297029947839837}, "weights_after": {"spy": 0.8, "dc": 0.2}}`

### Cost separation (80/20)

- D+C internal cost total (full D+C book): `0.07450000000000001`
- Outer sleeve rebalance cost total (80/20): `0.0011394390857299777`
- Internal costs are **not** charged again at the outer layer.

## 3. Full-precision reconciliation (80/20 vs SPY)

- SPY CAGR full: `0.11086935668037556`
- 80/20 CAGR full: `0.10944727378493369`
- CAGR gap full: `-0.0014220828954418785` = **-0.142208pp**
- Display explanation: Prior report used unrounded floats then formatted each CAGR to 2 decimals (10.94% and 11.09%), whose difference looks like -0.15pp, while the true gap is -0.142208pp. Rounded-display subtraction ≠ subtraction-then-round.
- MaxDD SPY / 80/20: `-0.5518940436853614` / `-0.4668297222930734`
- DD reduction full: `0.08506432139228803`
- CAGR cost per 1pp MaxDD: `0.00016717736321949958` (0.02% CAGR per 1pp)
- $10k end SPY / 80/20 / 60/40: `94970.027844` / `92400.956939` / `88472.200073`

## 4. Simple defensive benchmarks (pre-declared)

| Portfolio | CAGR | MaxDD | Sharpe | $10k | Max rel DD | Underwater |
|---|---:|---:|---:|---:|---:|---:|
| 100_spy | 11.09% | -55.19% | 0.6491 | 94970.03 | 0.00% | 0m |
| 80_20 | 10.94% | -46.68% | 0.7117 | 92400.96 | -21.83% | 210m |
| 60_40 | 10.72% | -37.53% | 0.7710 | 88472.20 | -39.45% | 210m |
| 80_20_ief | 9.70% | -44.90% | 0.7046 | 72617.77 | -35.28% | 210m |
| 80_20_cash | 9.25% | -46.71% | 0.6640 | 66400.03 | -37.75% | 210m |
| 80_20_gld | 11.47% | -44.57% | 0.7697 | 102214.60 | -27.48% | 181m |
| 90_10_ief | 10.41% | -50.28% | 0.6737 | 83292.81 | -19.37% | 210m |
| bench_60_40_ief | 8.43% | -31.53% | 0.7966 | 56606.24 | -57.76% | 210m |

- 20% D+C better MaxDD than all simple 20% defenses: **False**
- CAGR vs 80/20 IEF: **1.2415pp**
- Pairwise (CAGR edge / MaxDD edge vs candidate, pp): `{"80_20_ief": {"cagr_edge_pp": 1.2415406074312463, "maxdd_edge_pp": -1.7805708717853141}, "80_20_cash": {"cagr_edge_pp": 1.6992642365861954, "maxdd_edge_pp": 0.025056952524615816}, "80_20_gld": {"cagr_edge_pp": -0.5243136101679147, "maxdd_edge_pp": -2.114841185671368}, "90_10_ief": {"cagr_edge_pp": 0.5364837295203984, "maxdd_edge_pp": 3.597144080396586}}`
- Verdict: 20% D+C is NOT uniformly better than simple 20% defenses. vs 80/20 IEF: higher CAGR but worse MaxDD; vs 80/20 cash: similar MaxDD with higher CAGR; vs 80/20 GLD: lower CAGR and worse MaxDD on this sample. Keep 80/20 D+C as the frozen research candidate for paper tracking (momentum diversifier thesis), not because it dominates static sleeves.
- Pre-declared benchmarks only — no weight search. Paper default remains 80/20 SPY/D+C by prior freeze decision.

## 5. Look-through (80/20)

`{"avg_equity": 0.9029455047624434, "avg_bond": 0.013848274647435054, "avg_gold": 0.03197825697586153, "avg_cash": 0.05122796361426006, "avg_lookthrough_SPY": 0.806134443556644, "avg_lookthrough_QQQ": 0.038535946281868794, "avg_lookthrough_US_equity_overlap": 0.8446703898385128, "max_lookthrough_SPY": 0.9045223361786298, "target_outer_spy": 0.8, "target_outer_dc": 0.2}`

## 6. Paper-trading readiness

- Default candidate frozen: 80/20 SPY/D+C
- Conservative shadow: 60/40 SPY/D+C
- Opportunity-cost benchmark: 100% SPY
- Traditional benchmark: 60/40 SPY/IEF
- IBKR constraints implemented in `paper_trading` module when audit_pass is true.

