#!/usr/bin/env bash
# Start IB Gateway on-demand. Waits until API port is up AND stable (login complete).
set -euo pipefail

IBKR_HOME="/home/ec2-user/ibkr"
PORT="${IBKR_PORT:-4001}"
WAIT_SEC="${GATEWAY_WAIT_SEC:-600}"
STABLE_SEC="${GATEWAY_STABLE_SEC:-90}"

if ss -tlnp 2>/dev/null | grep -q ":${PORT} "; then
  echo "Gateway already listening on ${PORT}"
  exit 0
fi

echo "Starting IB Gateway — approve ONE 2FA on IBKR Mobile..."
sudo systemctl start ibgateway-ibc

deadline=$((SECONDS + WAIT_SEC))
while (( SECONDS < deadline )); do
  if ss -tlnp 2>/dev/null | grep -q ":${PORT} "; then
    echo "Port ${PORT} up; checking session stable for ${STABLE_SEC}s..."
    stable_deadline=$((SECONDS + STABLE_SEC))
    ok=true
    while (( SECONDS < stable_deadline )); do
      if ! ss -tlnp 2>/dev/null | grep -q ":${PORT} "; then
        echo "Port dropped — login may have failed (Login Messages / relogin loop)"
        ok=false
        break
      fi
      sleep 10
    done
    if $ok; then
      echo "Gateway session stable on ${PORT}"
      exit 0
    fi
  fi
  sleep 5
done

echo "ERROR: Gateway not stable on ${PORT} within ${WAIT_SEC}s" >&2
echo "Common causes:" >&2
echo "  1) Login Messages dialog — clear tasks at IBKR Client Portal" >&2
echo "  2) Relogin loop — check ReloginAfterSecondFactorAuthenticationTimeout=no" >&2
echo "  tail -f ${IBKR_HOME}/ibc/logs/ibc-*.txt" >&2
exit 1
