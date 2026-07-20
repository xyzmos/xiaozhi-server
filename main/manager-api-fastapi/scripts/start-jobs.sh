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
exec "${PYTHON}" -m app.jobs.worker
