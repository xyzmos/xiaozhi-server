#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPOSITORY_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
RUNTIME_ROOT="${REPOSITORY_ROOT}/.runtime"
LOG_DIR="${RUNTIME_ROOT}/logs"
FASTAPI_DIR="${REPOSITORY_ROOT}/main/manager-api-fastapi"
JAVA_API_DIR="${REPOSITORY_ROOT}/main/manager-api"
WEB_DIR="${REPOSITORY_ROOT}/main/manager-web"
SERVER_DIR="${REPOSITORY_ROOT}/main/xiaozhi-server"

MANAGER_API=fastapi
WAIT_SECONDS=0
CHECK_ONLY=false

usage() {
  cat <<'EOF'
Usage: scripts/restart-local-services.sh [options]

Restart the local manager API, manager web UI, and xiaozhi-server in named screen sessions.
The FastAPI manager is the default; the retained Java implementation remains selectable.

Options:
  --manager-api fastapi|java  Select the manager API implementation (default: fastapi)
  --wait SECONDS              Wait for all HTTP readiness probes
  --check                     Validate local prerequisites without starting or stopping anything
  -h, --help                  Show this help
EOF
}

fail() {
  echo "error: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is missing: $1"
}

require_executable() {
  [ -x "$1" ] || fail "required executable is missing: $1"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --manager-api)
      [ "$#" -ge 2 ] || fail "--manager-api requires fastapi or java"
      MANAGER_API=$2
      shift 2
      ;;
    --wait)
      [ "$#" -ge 2 ] || fail "--wait requires a non-negative number of seconds"
      WAIT_SECONDS=$2
      shift 2
      ;;
    --check)
      CHECK_ONLY=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown option: $1"
      ;;
  esac
done

case "${MANAGER_API}" in
  fastapi|java) ;;
  *) fail "--manager-api must be fastapi or java" ;;
esac
case "${WAIT_SECONDS}" in
  ''|*[!0-9]*) fail "--wait must be a non-negative integer" ;;
esac

require_command screen
require_command curl
require_command npm
require_executable "${WEB_DIR}/node_modules/.bin/vue-cli-service"

if [ -n "${XIAOZHI_PYTHON_BIN:-}" ]; then
  XIAOZHI_PYTHON=${XIAOZHI_PYTHON_BIN}
elif [ -x "${RUNTIME_ROOT}/py310/bin/python" ]; then
  XIAOZHI_PYTHON=${RUNTIME_ROOT}/py310/bin/python
else
  XIAOZHI_PYTHON=${REPOSITORY_ROOT}/.venv-xiaozhi/bin/python
fi
XIAOZHI_BIN_DIR=$(dirname "${XIAOZHI_PYTHON}")
require_executable "${XIAOZHI_PYTHON}"

if [ "${MANAGER_API}" = fastapi ]; then
  require_executable "${FASTAPI_DIR}/.venv/bin/python"
  require_executable "${FASTAPI_DIR}/scripts/start-api.sh"
  require_executable "${FASTAPI_DIR}/scripts/start-jobs.sh"
else
  require_executable "${RUNTIME_ROOT}/jdk/bin/java"
  require_executable "${RUNTIME_ROOT}/maven/bin/mvn"
fi

if [ "${CHECK_ONLY}" = true ]; then
  echo "Local service prerequisites are available (manager-api=${MANAGER_API})."
  exit 0
fi

mkdir -p "${LOG_DIR}"

stop_session() {
  session_name=$1
  session_ids=$(screen -list 2>/dev/null | awk -v wanted="${session_name}" '
    $1 ~ /^[0-9]+\./ {
      name = $1
      sub(/^[0-9]+\./, "", name)
      if (name == wanted) print $1
    }
  ')
  for session_id in ${session_ids}; do
    # Let foreground children (notably npm -> vue-cli-service) terminate before
    # removing the pseudo-terminal, otherwise they can survive as orphaned
    # listeners and make a later service bind to the wrong port.
    screen -S "${session_id}" -p 0 -X stuff "$(printf '\003')" >/dev/null 2>&1 || true
    remaining=10
    while [ "${remaining}" -gt 0 ] && \
      screen -list 2>/dev/null | awk '{print $1}' | grep -Fqx "${session_id}"; do
      sleep 1
      remaining=$((remaining - 1))
    done
    screen -S "${session_id}" -X quit >/dev/null 2>&1 || true
  done
}

stop_session xiaozhi-manager-api
stop_session xiaozhi-manager-api-jobs
stop_session xiaozhi-manager-web
stop_session xiaozhi-server

if [ "${MANAGER_API}" = fastapi ]; then
  screen -dmS xiaozhi-manager-api sh -c \
    'cd "$1" && exec "$2" >>"$3" 2>&1' \
    sh "${FASTAPI_DIR}" "${FASTAPI_DIR}/scripts/start-api.sh" "${LOG_DIR}/manager-api-fastapi.log"
  screen -dmS xiaozhi-manager-api-jobs sh -c \
    'cd "$1" && exec "$2" >>"$3" 2>&1' \
    sh "${FASTAPI_DIR}" "${FASTAPI_DIR}/scripts/start-jobs.sh" "${LOG_DIR}/manager-api-jobs.log"
  MANAGER_HEALTH=http://127.0.0.1:8002/xiaozhi/health/ready
else
  screen -dmS xiaozhi-manager-api sh -c \
    'cd "$1" && exec env JAVA_HOME="$2" PATH="$2/bin:$3:$PATH" "$3/mvn" "-Dmaven.repo.local=$4" spring-boot:run >>"$5" 2>&1' \
    sh "${JAVA_API_DIR}" "${RUNTIME_ROOT}/jdk" "${RUNTIME_ROOT}/maven/bin" \
    "${RUNTIME_ROOT}/m2" "${LOG_DIR}/manager-api-java.log"
  MANAGER_HEALTH=http://127.0.0.1:8002/xiaozhi/doc.html
fi

screen -dmS xiaozhi-manager-web sh -c \
  'cd "$1" && exec "$2" run serve >>"$3" 2>&1' \
  sh "${WEB_DIR}" "$(command -v npm)" "${LOG_DIR}/manager-web.log"
screen -dmS xiaozhi-server sh -c \
  'cd "$1" && exec env PATH="$3:$PATH" "$2" app.py >>"$4" 2>&1' \
  sh "${SERVER_DIR}" "${XIAOZHI_PYTHON}" "${XIAOZHI_BIN_DIR}" \
  "${LOG_DIR}/xiaozhi-server.log"

echo "Started screen sessions (manager-api=${MANAGER_API}):"
screen -list | grep -E 'xiaozhi-(manager-api|manager-api-jobs|manager-web|server)' || true

if [ "${WAIT_SECONDS}" -eq 0 ]; then
  exit 0
fi

DEADLINE=$(( $(date +%s) + WAIT_SECONDS ))
wait_for_url() {
  name=$1
  url=$2
  expected=${3:-}
  while [ "$(date +%s)" -le "${DEADLINE}" ]; do
    body=$(curl --fail --silent --show-error --max-time 2 "${url}" 2>/dev/null || true)
    if [ -n "${body}" ] && \
      { [ -z "${expected}" ] || printf '%s' "${body}" | grep -Fq "${expected}"; }; then
      echo "ready: ${name} (${url})"
      return 0
    fi
    sleep 1
  done
  echo "not ready before timeout: ${name} (${url})" >&2
  return 1
}

FAILED=0
wait_for_url manager-api "${MANAGER_HEALTH}" || FAILED=1
wait_for_url manager-web http://127.0.0.1:8001/ || FAILED=1
wait_for_url xiaozhi-server http://127.0.0.1:8003/mcp/vision/explain \
  'MCP Vision 接口运行正常' || FAILED=1
[ "${FAILED}" -eq 0 ] || fail "one or more local services failed readiness; inspect ${LOG_DIR}"
