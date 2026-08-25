# Live v1 tracking (committed to Git)

- `live_nav_ledger.csv` — append-only weekly NAV snapshots from IBKR
- `initial_nav.json` — baseline NAV set on first connect (or `--reset-initial-nav`)
- `live_performance.md` — human-readable return summary

Updated by: `btc-ma-qqq live-weekly --git-push`

**Does not modify** `frozen_oos_ledger.csv` (research OOS track).
