#!/usr/bin/env bash

set -euo pipefail

export SERVING_SQLITE_PATH="${SERVING_SQLITE_PATH:-/home/site/wwwroot/data/serving/transport_dashboard.db}"

exec python -m uvicorn transport_platform.api.app:app \
  --app-dir /home/site/wwwroot/src \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips "*"
