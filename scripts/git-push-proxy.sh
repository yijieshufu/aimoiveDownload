#!/usr/bin/env bash
set -euo pipefail

# Default to Clash mixed port; allow override by env vars.
PROXY_HOST="${PROXY_HOST:-127.0.0.1}"
PROXY_PORT="${PROXY_PORT:-7897}"
PROXY_URL="http://${PROXY_HOST}:${PROXY_PORT}"

echo "Using proxy: ${PROXY_URL}"
HTTPS_PROXY="${PROXY_URL}" HTTP_PROXY="${PROXY_URL}" git push origin HEAD "$@"
