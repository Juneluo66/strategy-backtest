#!/usr/bin/env bash
# Weekly v1 Lark notify ONLY — never starts IB Gateway / never trades.
#
# Flow (avoids stale-week pushes):
#   1) fetch --refresh  (Yahoo BTC/QQQ/SHY)
#   2) oos-append       (append completed OOS weeks; never rewrite)
#   3) live-notify      (latest week signal + local capital summary → Lark)
#
# Cron: Mon 09:20 America/New_York (before US open)
#   Beijing: Mon 21:20 (EDT) / 22:20 (EST)
#
# Catch-up: FORCE=1 bash scripts/weekly_notify_v1.sh
set -eu

REPO="/home/ec2-user/strategy-backtest"
cd "$REPO/btc_ma_qqq_shy" || exit 1
LOG_DIR="$REPO/btc_ma_qqq_shy/reports/live"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/weekly_notify.log"

# Cron PATH is minimal — pin absolute CLI path.
HOME="/home/ec2-user"
PATH="/home/ec2-user/.local/bin:/usr/local/bin:/usr/bin:/bin"
BTC_CLI="/home/ec2-user/.local/bin/btc-ma-qqq"

log() {
  echo "[$(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S %Z')] $*" | tee -a "$LOG_FILE"
}

if [ "${FORCE:-0}" != "1" ]; then
  DOW_ET="$(TZ=America/New_York date +%u)"
  if [ "$DOW_ET" != "1" ]; then
    log "Skip: not Monday ET (ET=$(TZ=America/New_York date))"
    exit 0
  fi
fi

# Ensure console script exists (CLI itself loads .env via python-dotenv).
/usr/bin/python3 -m pip install -q -e ".[live]" >>"$LOG_FILE" 2>&1 || true

if [ ! -x "$BTC_CLI" ]; then
  log "ERROR: missing $BTC_CLI"
  exit 1
fi

log "Step 1/3: refresh market data..."
"$BTC_CLI" fetch --refresh >>"$LOG_FILE" 2>&1 || {
  log "ERROR: fetch --refresh failed"
  exit 1
}

log "Step 2/3: append completed OOS weeks..."
"$BTC_CLI" oos-append >>"$LOG_FILE" 2>&1 || {
  log "WARN: oos-append failed (continuing to notify with refreshed signal)"
}

log "Step 3/3: Lark notify (latest week signal)..."
"$BTC_CLI" live-notify >>"$LOG_FILE" 2>&1
RC=$?
if [ "$RC" -ne 0 ]; then
  log "ERROR: live-notify failed rc=$RC"
  exit "$RC"
fi
log "Done."
