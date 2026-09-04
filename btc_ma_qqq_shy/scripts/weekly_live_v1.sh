#!/usr/bin/env bash
# Weekly v1:
#   1) live-signal — NO Gateway
#   2) ~09:20 ET start Gateway → ONE 2FA (~10 min before US open)
#   3) 09:35 ET market orders + ledger
#   4) stop Gateway
#
# Cron: Mon 09:20 America/New_York
#   Beijing: Mon 21:20 (EDT) / 22:20 (EST)
#   US open 09:30 ET → Beijing 21:30 (EDT) / 22:30 (EST)
set -euo pipefail

REPO="/home/ec2-user/strategy-backtest"
cd "$REPO/btc_ma_qqq_shy"
LOG_DIR="$REPO/btc_ma_qqq_shy/reports/live"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/weekly_cron.log"

log() { echo "[$(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S %Z')] $*" | tee -a "$LOG_FILE"; }

if [[ -f "$REPO/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source <(grep -v '^\s*#' "$REPO/.env" | sed 's/^/export /')
  set +a
fi

DOW_ET="$(TZ=America/New_York date +%u)"
HOUR_ET="$(TZ=America/New_York date +%H)"
MIN_ET="$(TZ=America/New_York date +%M)"
HOUR_ET=$((10#$HOUR_ET))
MIN_ET=$((10#$MIN_ET))
MINUTES=$((HOUR_ET * 60 + MIN_ET))

if [[ "$DOW_ET" != "1" ]] || (( MINUTES < 9 * 60 + 15 )) || (( MINUTES >= 11 * 60 )); then
  log "Skip: not Mon ET 09:15–11:00 (ET=$(TZ=America/New_York date), BJ=$(TZ=Asia/Shanghai date))"
  exit 0
fi

python3 -m pip install -q -e ".[live]" 2>/dev/null || pip3 install -q -e ".[live]"

log "Phase 1: compute signal (no Gateway)..."
btc-ma-qqq live-signal 2>&1 | tee -a "$LOG_FILE"

log "Phase 2: start Gateway (~10 min before US open) — approve ONE 2FA..."
bash "$REPO/btc_ma_qqq_shy/scripts/start_gateway_for_trade.sh" | tee -a "$LOG_FILE"

TARGET_MIN=$((9 * 60 + 35))
while true; do
  H="$(TZ=America/New_York date +%H)"; M="$(TZ=America/New_York date +%M)"
  NOW=$((10#$H * 60 + 10#$M))
  if (( NOW >= TARGET_MIN )); then
    break
  fi
  left=$((TARGET_MIN - NOW))
  log "Session held; waiting for ET 09:35 (${left} min)..."
  sleep 30
done

log "Phase 3: market orders + ledger..."
btc-ma-qqq live-weekly --confirm --git-push 2>&1 | tee -a "$LOG_FILE"

bash "$REPO/btc_ma_qqq_shy/scripts/stop_gateway.sh" | tee -a "$LOG_FILE"
log "Weekly v1 complete."
