#!/usr/bin/env bash

set -euo pipefail

[[ -f "${SERVING_SQLITE_PATH:-}" ]] || export SERVING_SQLITE_PATH="${PWD}/data/serving/transport_dashboard.db"

exec python -m uvicorn transport_platform.api.app:app \
  --app-dir "${PWD}/src" \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips "*"
