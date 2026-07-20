#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
REPOSITORY_ROOT=$(CDPATH= cd -- "${TARGET_DIR}/../.." && pwd)
RUNTIME="${REPOSITORY_ROOT}/.runtime"
JAVA_DIR="${REPOSITORY_ROOT}/main/manager-api"
STATE_DIR="${TARGET_DIR}/.test-runtime/contract"
JAVA_PORT="${CONTRACT_JAVA_PORT:-18082}"
FASTAPI_PORT="${CONTRACT_FASTAPI_PORT:-18083}"
MOCK_PORT="${CONTRACT_MOCK_PORT:-18084}"
JAVA_PID=""
FASTAPI_PID=""
MOCK_PID=""

mkdir -p "${STATE_DIR}"

stop_process() {
  pid=$1
  if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
    children=$(pgrep -P "${pid}" 2>/dev/null || true)
    if [ -n "${children}" ]; then
      kill ${children} 2>/dev/null || true
    fi
    kill "${pid}" 2>/dev/null || true
    wait "${pid}" 2>/dev/null || true
  fi
}

cleanup() {
  stop_process "${FASTAPI_PID}"
  stop_process "${JAVA_PID}"
  stop_process "${MOCK_PID}"
}
trap cleanup EXIT INT TERM

wait_for_url() {
  name=$1
  url=$2
  attempts=0
  until curl --fail --silent --show-error "${url}" >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [ "${attempts}" -ge 240 ]; then
      echo "Timed out waiting for ${name}; inspect ${STATE_DIR}." >&2
      return 1
    fi
    sleep 0.25
  done
}

assert_clean_runtime_logs() {
  for log in "${STATE_DIR}/fastapi.log" "${STATE_DIR}/external-mock.log"; do
    if rg -n -i 'UnsupportedFieldAttributeWarning|Traceback|\bERROR\b|\bWARNING\b' "${log}"; then
      echo "Unexpected warning or error in ${log}." >&2
      return 1
    fi
  done

  # Logback's own bootstrap diagnostics contain tokens such as ERROR_FILE.
  # Runtime application records start with the configured full ISO date.
  java_errors=$(rg -n '^[0-9]{4}-[0-9]{2}-[0-9]{2} .*ERROR.* - ' "${STATE_DIR}/java.log" || true)
  if [ -n "${java_errors}" ]; then
    java_error_count=$(printf '%s\n' "${java_errors}" | wc -l | tr -d ' ')
    missing_body_errors=$(printf '%s\n' "${java_errors}" | rg -F 'Required request body is missing:' | wc -l | tr -d ' ')
    missing_device_errors=$(printf '%s\n' "${java_errors}" | rg -F "Required request header 'Device-Id'" | wc -l | tr -d ' ')
    object_array_errors=$(printf '%s\n' "${java_errors}" | rg -F 'JSON parse error: Cannot deserialize value of type' | wc -l | tr -d ' ')
    missing_query_errors=$(printf '%s\n' "${java_errors}" | rg -e "Required request parameter '(ids|modelType|id)' for method parameter type String is not present" | wc -l | tr -d ' ')
    multipart_errors=$(printf '%s\n' "${java_errors}" | rg -F 'Current request is not a multipart request' | wc -l | tr -d ' ')
    caller_mac_errors=$(printf '%s\n' "${java_errors}" | rg -F 'Cannot invoke "String.toLowerCase()" because "callerMac" is null' | wc -l | tr -d ' ')
    null_message_errors=$(printf '%s\n' "${java_errors}" | rg -e ' - null$' | wc -l | tr -d ' ')
    blank_message_errors=$(printf '%s\n' "${java_errors}" | rg -e ' - $' | wc -l | tr -d ' ')
    if [ "${java_error_count}" -ne 36 ] \
      || [ "${missing_body_errors}" -ne 13 ] \
      || [ "${missing_device_errors}" -ne 5 ] \
      || [ "${object_array_errors}" -ne 8 ] \
      || [ "${missing_query_errors}" -ne 4 ] \
      || [ "${multipart_errors}" -ne 3 ] \
      || [ "${caller_mac_errors}" -ne 1 ] \
      || [ "${null_message_errors}" -ne 1 ] \
      || [ "${blank_message_errors}" -ne 1 ]; then
      printf '%s\n' "${java_errors}" >&2
      echo "The two 154-route safe surfaces did not produce the exact expected Java baseline error profile." >&2
      return 1
    fi
    unexpected_java_errors=$(
      printf '%s\n' "${java_errors}" |
        rg -v -e "Required request header 'Device-Id' for method parameter type String is not present" \
          -e 'Required request body is missing:' \
          -e 'JSON parse error: Cannot deserialize value of type .* from Object value \(token .*START_OBJECT.*\)' \
          -e "Required request parameter '(ids|modelType|id)' for method parameter type String is not present" \
          -e 'Current request is not a multipart request' \
          -e 'Cannot invoke "String.toLowerCase\(\)" because "callerMac" is null' \
          -e ' - null$' \
          -e ' - $' || true
    )
    if [ -n "${unexpected_java_errors}" ]; then
      printf '%s\n' "${unexpected_java_errors}" >&2
      echo "Unexpected Java baseline error; only the counted safe surface-validation paths are allowed." >&2
      return 1
    fi
  fi
}

start_java() {
  (
    cd "${JAVA_DIR}"
    JAVA_HOME="${RUNTIME}/jdk" \
    PATH="${RUNTIME}/jdk/bin:${RUNTIME}/maven/bin:${PATH}" \
      exec "${RUNTIME}/maven/bin/mvn" \
      -Dmaven.repo.local="${RUNTIME}/m2" \
      -DskipTests spring-boot:run \
      -Dspring-boot.run.arguments="--server.port=${JAVA_PORT} \
--spring.datasource.druid.url=jdbc:mysql://127.0.0.1:${TEST_MYSQL_PORT}/manager_java_test?useUnicode=true&characterEncoding=UTF-8&serverTimezone=Asia/Shanghai&nullCatalogMeansCurrent=true&allowMultiQueries=true \
--spring.datasource.druid.username=xiaozhi_test \
--spring.datasource.druid.password=isolated-test-only \
--spring.data.redis.host=127.0.0.1 \
--spring.data.redis.port=${TEST_REDIS_PORT} \
--spring.data.redis.database=1 \
--spring.data.redis.password="
  ) >"${STATE_DIR}/java.log" 2>&1 &
  JAVA_PID=$!
  wait_for_url "Java baseline" "http://127.0.0.1:${JAVA_PORT}/xiaozhi/ota/"
}

start_mock() {
  (
    cd "${TARGET_DIR}"
    exec .venv/bin/uvicorn tests.compatibility.external_mock:app \
      --host 127.0.0.1 --port "${MOCK_PORT}" --log-level warning
  ) >"${STATE_DIR}/external-mock.log" 2>&1 &
  MOCK_PID=$!
  wait_for_url "external-service mock" "http://127.0.0.1:${MOCK_PORT}/health"
}

start_fastapi() {
  (
    cd "${TARGET_DIR}"
    APP_ENVIRONMENT=test \
    APP_DATABASE_URL="${TEST_FASTAPI_DATABASE_URL}" \
    APP_REDIS_URL="${TEST_FASTAPI_REDIS_URL}" \
    APP_SERVER_SECRET_OVERRIDE=contract-server-secret \
    APP_UPLOAD_DIR="${STATE_DIR}/uploads" \
    APP_LOG_LEVEL=WARNING \
      exec .venv/bin/uvicorn app.main:app \
      --host 127.0.0.1 --port "${FASTAPI_PORT}" --log-level warning
  ) >"${STATE_DIR}/fastapi.log" 2>&1 &
  FASTAPI_PID=$!
  wait_for_url "FastAPI target" "http://127.0.0.1:${FASTAPI_PORT}/xiaozhi/health/ready"
}

cd "${TARGET_DIR}"

./scripts/isolated-env.sh reset
./scripts/isolated-env.sh migrate
eval "$(./scripts/isolated-env.sh env)"

start_mock

# The retained Java startup creates the SM2 key pair on an empty schema.
start_java
.venv/bin/python -m tests.compatibility.seed_contract_data \
  --mysql-port "${TEST_MYSQL_PORT}" --mock-port "${MOCK_PORT}"

# Reload Java after the deterministic fixture replaced server params.  FLUSHALL
# is safe here because this is the dedicated Redis on TEST_REDIS_PORT and the
# FastAPI target has not started yet.
stop_process "${JAVA_PID}"
JAVA_PID=""
"${RUNTIME}/redis/bin/redis-cli" -h 127.0.0.1 -p "${TEST_REDIS_PORT}" FLUSHALL >/dev/null
start_java
start_fastapi

# Restore fixed dates after Java startup and allow no stale async baseline write
# to leak into the first read-only comparison.
.venv/bin/python -m tests.compatibility.seed_contract_data \
  --mysql-port "${TEST_MYSQL_PORT}" --mock-port "${MOCK_PORT}"
sleep 1
.venv/bin/python -m tests.compatibility.seed_contract_data \
  --mysql-port "${TEST_MYSQL_PORT}" --mock-port "${MOCK_PORT}"

TEST_FASTAPI_DATABASE_URL="${TEST_FASTAPI_DATABASE_URL}" \
TEST_FASTAPI_REDIS_URL="${TEST_FASTAPI_REDIS_URL}" \
APP_DATABASE_URL="${TEST_FASTAPI_DATABASE_URL}" \
APP_REDIS_URL="${TEST_FASTAPI_REDIS_URL}" \
APP_ENVIRONMENT=test \
  .venv/bin/pytest -q tests/integration/test_isolated_runtime.py

.venv/bin/python -m tests.compatibility.route_surface_runner \
  --java-base "http://127.0.0.1:${JAVA_PORT}/xiaozhi" \
  --fastapi-base "http://127.0.0.1:${FASTAPI_PORT}/xiaozhi" \
  --mock-base "http://127.0.0.1:${MOCK_PORT}" \
  --mysql-port "${TEST_MYSQL_PORT}" \
  --output compatibility/route-surface-results.json

.venv/bin/python -m tests.compatibility.authenticated_route_runner \
  --java-base "http://127.0.0.1:${JAVA_PORT}/xiaozhi" \
  --fastapi-base "http://127.0.0.1:${FASTAPI_PORT}/xiaozhi" \
  --mock-base "http://127.0.0.1:${MOCK_PORT}" \
  --mysql-port "${TEST_MYSQL_PORT}" \
  --output compatibility/authenticated-route-results.json

.venv/bin/python -m tests.compatibility.differential_runner \
  --java-base "http://127.0.0.1:${JAVA_PORT}/xiaozhi" \
  --fastapi-base "http://127.0.0.1:${FASTAPI_PORT}/xiaozhi" \
  --mock-base "http://127.0.0.1:${MOCK_PORT}" \
  --mysql-port "${TEST_MYSQL_PORT}" \
  --output compatibility/contract-results.json

.venv/bin/python -m tests.compatibility.seed_contract_data \
  --mysql-port "${TEST_MYSQL_PORT}" --mock-port "${MOCK_PORT}"
.venv/bin/python -m tests.compatibility.performance_runner \
  --java-base "http://127.0.0.1:${JAVA_PORT}/xiaozhi" \
  --fastapi-base "http://127.0.0.1:${FASTAPI_PORT}/xiaozhi" \
  --requests 60 --concurrency 6 --warmup 10 \
  --output compatibility/performance-results.json

assert_clean_runtime_logs

echo "Isolated integration, 154-route unauthenticated and authenticated surfaces, deep differential, and performance tests passed."
