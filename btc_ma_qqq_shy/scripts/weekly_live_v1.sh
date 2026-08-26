#!/usr/bin/env bash
# Weekly v1 live update: IBKR rebalance + NAV ledger + GitHub push
# Cron example (US market open Monday, ET — adjust for your host TZ):
#   35 14 * * 1  bash /home/ec2-user/strategy-backtest/btc_ma_qqq_shy/scripts/weekly_live_v1.sh
set -euo pipefail

REPO="/home/ec2-user/strategy-backtest"
cd "$REPO/btc_ma_qqq_shy"

if [[ -f "$REPO/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source <(grep -v '^\s*#' "$REPO/.env" | sed 's/^/export /')
  set +a
fi

python3 -m pip install -q -e ".[live]" 2>/dev/null || pip3 install -q -e ".[live]"

btc-ma-qqq live-weekly --confirm --git-push
