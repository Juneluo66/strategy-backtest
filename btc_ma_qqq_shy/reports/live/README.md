# Live v1 tracking (committed to Git)

- `capital_pool.json` — locked strategy cash envelope (isolated from other account assets)
- `initial_nav.json` — baseline capital basis for return calculation
- `live_nav_ledger.csv` — append-only weekly pool NAV snapshots
- `live_performance.md` — human-readable return summary

Updated by: `btc-ma-qqq live-weekly --confirm --git-push`

**Capital rules**
- Initial lock: `live-init --capital <USD> --confirm`
- Extra cash only via: `live-inject-capital <USD> --confirm`
- Orders require `--confirm` (preview first with `live-preview`)

**Does not modify** `frozen_oos_ledger.csv` (research OOS track).
