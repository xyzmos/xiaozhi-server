#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
PYTHON="${PYTHON_BIN:-${PROJECT_DIR}/.venv/bin/python}"

if [ ! -x "${PYTHON}" ]; then
  echo "Python environment is missing; run 'uv sync --locked' in ${PROJECT_DIR}" >&2
  exit 1
fi

cd "${PROJECT_DIR}"
exec "${PYTHON}" -m uvicorn app.main:app \
  --host "${APP_HOST:-0.0.0.0}" \
  --port "${APP_PORT:-8002}" \
  --workers "${APP_WORKERS:-1}" \
  --timeout-graceful-shutdown "${APP_GRACEFUL_SHUTDOWN_SECONDS:-30}" \
  --proxy-headers \
  --forwarded-allow-ips "${APP_FORWARDED_ALLOW_IPS:-127.0.0.1}"
