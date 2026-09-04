#!/usr/bin/env bash
# Stop on-demand IB Gateway after trading (avoids idle 2FA loops).
set -euo pipefail
sudo systemctl stop ibgateway-ibc || true
echo "Gateway stopped"
