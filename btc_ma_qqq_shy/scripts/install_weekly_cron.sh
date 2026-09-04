#!/usr/bin/env bash
# Install / refresh weekly Lark-notify cron (NO IBKR login / NO trading).
#
# Usage:
#   bash scripts/install_weekly_cron.sh
#   bash scripts/install_weekly_cron.sh --show
#   bash scripts/install_weekly_cron.sh --remove
set -euo pipefail

REPO="/home/ec2-user/strategy-backtest"
SCRIPT="$REPO/btc_ma_qqq_shy/scripts/weekly_notify_v1.sh"
MARKER_BEGIN="# BEGIN btc-ma-qqq-shy weekly v1"
MARKER_END="# END btc-ma-qqq-shy weekly v1"

# Mon 09:20 ET ≈ Beijing 21:20 (EDT) / 22:20 (EST) — before US open
BLOCK=$(cat <<EOF
$MARKER_BEGIN
CRON_TZ=America/New_York
20 9 * * 1 $SCRIPT
$MARKER_END
EOF
)

chmod +x "$SCRIPT" \
  "$REPO/btc_ma_qqq_shy/scripts/install_weekly_cron.sh" \
  "$REPO/btc_ma_qqq_shy/scripts/weekly_live_v1.sh" 2>/dev/null || true
chmod +x "$REPO/btc_ma_qqq_shy/scripts/start_gateway_for_trade.sh" \
  "$REPO/btc_ma_qqq_shy/scripts/stop_gateway.sh" 2>/dev/null || true

_strip_block() {
  awk -v b="$MARKER_BEGIN" -v e="$MARKER_END" '
    $0 == b { skip=1; next }
    skip && $0 == e { skip=0; next }
    skip { next }
    { print }
  '
}

show() {
  echo "=== current crontab ==="
  crontab -l 2>/dev/null || echo "(empty)"
  echo
  echo "Mode: Lark notify ONLY (no IBKR Gateway / no auto trade)"
  echo "Cron: Mon 09:20 America/New_York"
  echo "  Beijing 夏令时: Mon 21:20"
  echo "  Beijing 冬令时: Mon 22:20"
  echo "Message: 本周应买谁 + 本地资金池/上周摘要"
}

remove() {
  local tmp
  tmp="$(mktemp)"
  if crontab -l >/dev/null 2>&1; then
    crontab -l | _strip_block > "$tmp"
    crontab "$tmp"
  fi
  rm -f "$tmp"
  echo "Removed weekly cron block (if present)."
}

install() {
  local tmp existing
  tmp="$(mktemp)"
  existing="$(mktemp)"
  crontab -l 2>/dev/null | _strip_block > "$existing" || true
  {
    cat "$existing"
    echo
    echo "$BLOCK"
  } > "$tmp"
  crontab "$tmp"
  rm -f "$tmp" "$existing"
  echo "Installed:"
  echo "$BLOCK"
  echo
  show
}

case "${1:-}" in
  --show) show ;;
  --remove) remove; show ;;
  ""|--install) install ;;
  *)
    echo "Usage: $0 [--install|--show|--remove]" >&2
    exit 2
    ;;
esac
