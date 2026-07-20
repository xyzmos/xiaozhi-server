#!/bin/sh
set -eu

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec uvicorn app.main:app \
  --host "${APP_HOST:-0.0.0.0}" \
  --port "${APP_PORT:-8002}" \
  --workers "${APP_WORKERS:-2}" \
  --timeout-graceful-shutdown "${APP_GRACEFUL_SHUTDOWN_SECONDS:-30}" \
  --proxy-headers \
  --forwarded-allow-ips "${APP_FORWARDED_ALLOW_IPS:-127.0.0.1}"
