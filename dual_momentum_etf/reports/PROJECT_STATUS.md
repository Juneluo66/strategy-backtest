# Dual Momentum ETF — Project Status

- Updated: `2026-08-12T03:07:07Z`
- config_hash: `8725aaf1874386e68016e9e7ad290f09b8528a34ecf7857f350acfa8a208b1c2`

## Frozen decisions

- **D+C rules frozen**: `attribution_DC` — score 0.6·R5M+0.4·R12M, price>10m SMA,
  trend consistency **3/6/12 all > 0**, category max 1, top-2 equal weight, no hysteresis, no regime B.
- **Do not** retune 3/6/12, category constraints, or search new sleeve weights.
- **Default paper candidate**: **80% SPY + 20% D+C**
- **Conservative shadow only**: 60% SPY + 40% D+C (not an optimized alternative).

## Final audit

- Gate: **PASS**
- Report: `reports/dc_sleeve_final_audit.md`
- Sample: `2005-03-01` → `2026-08-10`
- 80/20 vs SPY CAGR gap (full precision): `-0.142208pp`
- 20% D+C vs simple 20% defenses (MaxDD better than all): **False**
- Verdict: 20% D+C is NOT uniformly better than simple 20% defenses. vs 80/20 IEF: higher CAGR but worse MaxDD; vs 80/20 cash: similar MaxDD with higher CAGR; vs 80/20 GLD: lower CAGR and worse MaxDD on this sample. Keep 80/20 D+C as the frozen research candidate for paper tracking (momentum diversifier thesis), not because it dominates static sleeves.

## Paper trading (IBKR constraints, no live orders)

- Status: **seeded** (research simulator)
- Config: `configs/paper_trading.yaml`
- Books:
  - `candidate_80_20_dc` (default_paper_candidate): final_nav≈917612.6681891357, log_events=1106
  - `opp_cost_100_spy` (opportunity_cost_benchmark): final_nav≈941897.6994970848, log_events=2
  - `shadow_60_40_dc` (conservative_shadow): final_nav≈875506.2477436773, log_events=1106
  - `traditional_60_40_ief` (traditional_benchmark): final_nav≈542763.0708170498, log_events=780
- Artifacts: latest `reports/runs/*_paper_*` + `reports/paper_books_summary.json`

## Parallel books maintained

1. `candidate_80_20_dc` — formal default
2. `opp_cost_100_spy` — opportunity cost
3. `shadow_60_40_dc` — conservative shadow
4. `traditional_60_40_ief` — traditional 60/40

