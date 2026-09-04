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

**Weekly automation (notify only):** Mon **09:20 ET**（北京 **21:20 夏令 / 22:20 冬令**）发 Lark。  
流程：`fetch --refresh` → `oos-append` → `live-notify`（用**最新一周**信号，避免推过期周）。**不登录 IBKR，不下单。**

```bash
# Lark webhook in btc_ma_qqq_shy/.env (see .env.example)
bash scripts/install_weekly_cron.sh
btc-ma-qqq live-notify --dry-run   # preview message (still refreshes data)
btc-ma-qqq live-notify             # refresh + send to Lark
btc-ma-qqq live-signal             # refresh + signal only
FORCE=1 bash scripts/weekly_notify_v1.sh   # manual catch-up
```

Scripts: `install_weekly_cron.sh`, `weekly_notify_v1.sh`  
Fills audit: `reports/live/fills.csv`, pending: `reports/live/pending_order.json`

IBKR Gateway 仅在你明确要求时再启；默认 cron **不会**启动，成交以你同步的实盘为准。
