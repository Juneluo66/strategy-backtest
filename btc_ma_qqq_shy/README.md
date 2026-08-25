# BTC MA → QQQ / SHY

Independent email-claim audit: weekly check whether **BTC-USD** is above its
50-day SMA **and** 20-day momentum is positive; if so hold **QQQ**, else **SHY**.
Compare drawdown and risk-adjusted returns to **SPY** and **QQQ** from 2014.

```bash
pip install -e .
btc-ma-qqq full-audit      # NAV / claim check
btc-ma-qqq diagnostics    # return timing vs risk timing battery
btc-ma-qqq oos-append      # append-only frozen OOS ledger (cutoff 2026-08-07)
btc-ma-qqq oos-status
btc-ma-qqq risk-predict    # forward RV / drawdown classification vs VIX
btc-ma-qqq risk-matched    # vs occupancy / vol / beta-matched static
```

**Frozen OOS:** `configs/frozen.yaml` → `oos.cutoff_date: 2026-08-07`.  
Ledger: `reports/frozen_oos_ledger.csv` — never rewrite history; changing SMA/MOM resets the clock.

Reports:
- `reports/frozen_oos_ledger.csv`
- `reports/risk_prediction.md`
- `reports/risk_matched_benchmarks.md`
- `reports/email_claim_audit.md`
- `reports/return_vs_risk_timing.md`
- `reports/implementation_reconciliation.md`
- `reports/costs_execution_timestamps.md`
- `reports/mechanism_partial_r2.md`

Frozen rules: `configs/frozen.yaml` (do not retune after seeing results).

Does not modify IBKR, production, or other strategy configs.

## Live v1 (IBKR)

Requires **IB Gateway or TWS** logged in on a host reachable from this machine.

```bash
pip install -e ".[live]"
# Edit strategy-backtest/.env — IBKR_HOST, IBKR_PORT (see .env.example)
btc-ma-qqq live-status          # read account + current signal
btc-ma-qqq live-weekly --dry-run
btc-ma-qqq live-weekly --git-push   # rebalance + ledger + push GitHub
```

Weekly cron: `scripts/weekly_live_v1.sh`

Live reports (committed): `reports/live/live_nav_ledger.csv`, `live_performance.md`

Separate from research `frozen_oos_ledger.csv`.
