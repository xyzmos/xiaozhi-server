#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
REPOSITORY_ROOT=$(CDPATH= cd -- "${TARGET_DIR}/../.." && pwd)
RUNTIME="${REPOSITORY_ROOT}/.runtime"
STATE_DIR="${TARGET_DIR}/.test-runtime"
MYSQL_BASE="${RUNTIME}/mysql"
MYSQL_PORT="${TEST_MYSQL_PORT:-13316}"
MYSQL_DATA="${STATE_DIR}/mysql-data"
MYSQL_SOCKET="${STATE_DIR}/mysql.sock"
MYSQL_PID="${STATE_DIR}/mysql.pid"
MYSQL_LOG="${STATE_DIR}/mysql.log"
REDIS_PORT="${TEST_REDIS_PORT:-16379}"
REDIS_DIR="${STATE_DIR}/redis-data"
REDIS_PID="${STATE_DIR}/redis.pid"
REDIS_LOG="${STATE_DIR}/redis.log"
TEST_USER="xiaozhi_test"
TEST_PASSWORD="isolated-test-only"
JAVA_DATABASE="manager_java_test"
FASTAPI_DATABASE="manager_fastapi_test"

require_binaries() {
  for binary in "${MYSQL_BASE}/bin/mysqld" "${MYSQL_BASE}/bin/mysql" \
    "${RUNTIME}/redis/bin/redis-server" "${RUNTIME}/redis/bin/redis-cli"; do
    if [ ! -x "${binary}" ]; then
      echo "Missing isolated-test binary: ${binary}" >&2
      exit 1
    fi
  done
}

mysql_ready() {
  "${MYSQL_BASE}/bin/mysqladmin" --protocol=SOCKET --socket="${MYSQL_SOCKET}" -uroot ping >/dev/null 2>&1
}

redis_ready() {
  "${RUNTIME}/redis/bin/redis-cli" -h 127.0.0.1 -p "${REDIS_PORT}" ping >/dev/null 2>&1
}

wait_until() {
  description=$1
  shift
  attempts=0
  until "$@"; do
    attempts=$((attempts + 1))
    if [ "${attempts}" -ge 100 ]; then
      echo "Timed out waiting for ${description}" >&2
      exit 1
    fi
    sleep 0.1
  done
}

start_mysql() {
  mkdir -p "${STATE_DIR}" "${MYSQL_DATA}"
  if [ ! -d "${MYSQL_DATA}/mysql" ]; then
    "${MYSQL_BASE}/bin/mysqld" --no-defaults --initialize-insecure \
      --basedir="${MYSQL_BASE}" --datadir="${MYSQL_DATA}" --log-error="${MYSQL_LOG}"
  fi
  if ! mysql_ready; then
    "${MYSQL_BASE}/bin/mysqld" --no-defaults --daemonize \
      --basedir="${MYSQL_BASE}" --datadir="${MYSQL_DATA}" --port="${MYSQL_PORT}" \
      --socket="${MYSQL_SOCKET}" --pid-file="${MYSQL_PID}" --log-error="${MYSQL_LOG}" \
      --bind-address=127.0.0.1 --mysqlx=0 --skip-name-resolve \
      --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci \
      --default-time-zone=+08:00
    wait_until "isolated MySQL" mysql_ready
  fi
  "${MYSQL_BASE}/bin/mysql" --protocol=SOCKET --socket="${MYSQL_SOCKET}" -uroot \
    -e "CREATE DATABASE IF NOT EXISTS ${JAVA_DATABASE} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; CREATE DATABASE IF NOT EXISTS ${FASTAPI_DATABASE} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; CREATE USER IF NOT EXISTS '${TEST_USER}'@'127.0.0.1' IDENTIFIED BY '${TEST_PASSWORD}'; GRANT ALL PRIVILEGES ON ${JAVA_DATABASE}.* TO '${TEST_USER}'@'127.0.0.1'; GRANT ALL PRIVILEGES ON ${FASTAPI_DATABASE}.* TO '${TEST_USER}'@'127.0.0.1'; FLUSH PRIVILEGES;"
}

start_redis() {
  mkdir -p "${REDIS_DIR}"
  if ! redis_ready; then
    "${RUNTIME}/redis/bin/redis-server" --daemonize yes --bind 127.0.0.1 \
      --port "${REDIS_PORT}" --pidfile "${REDIS_PID}" --dir "${REDIS_DIR}" \
      --logfile "${REDIS_LOG}" --save "" --appendonly no --databases 16
    wait_until "isolated Redis" redis_ready
  fi
}

start() {
  require_binaries
  start_mysql
  start_redis
  echo "Isolated MySQL ${MYSQL_PORT} and Redis ${REDIS_PORT} are ready."
}

stop() {
  if redis_ready; then
    "${RUNTIME}/redis/bin/redis-cli" -h 127.0.0.1 -p "${REDIS_PORT}" shutdown nosave >/dev/null
  fi
  if mysql_ready; then
    "${MYSQL_BASE}/bin/mysqladmin" --protocol=SOCKET --socket="${MYSQL_SOCKET}" -uroot shutdown
  fi
  echo "Isolated services stopped."
}

reset() {
  start
  "${MYSQL_BASE}/bin/mysql" --protocol=SOCKET --socket="${MYSQL_SOCKET}" -uroot \
    -e "DROP DATABASE IF EXISTS ${JAVA_DATABASE}; DROP DATABASE IF EXISTS ${FASTAPI_DATABASE}; CREATE DATABASE ${JAVA_DATABASE} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; CREATE DATABASE ${FASTAPI_DATABASE} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; GRANT ALL PRIVILEGES ON ${JAVA_DATABASE}.* TO '${TEST_USER}'@'127.0.0.1'; GRANT ALL PRIVILEGES ON ${FASTAPI_DATABASE}.* TO '${TEST_USER}'@'127.0.0.1';"
  "${RUNTIME}/redis/bin/redis-cli" -h 127.0.0.1 -p "${REDIS_PORT}" flushall >/dev/null
  echo "Only the isolated test schemas and isolated Redis instance were reset."
}

migrate_one() {
  database=$1
  LIQUIBASE_URL="jdbc:mysql://127.0.0.1:${MYSQL_PORT}/${database}?useUnicode=true&characterEncoding=UTF-8&serverTimezone=Asia/Shanghai&allowMultiQueries=true" \
  LIQUIBASE_USERNAME="${TEST_USER}" \
  LIQUIBASE_PASSWORD="${TEST_PASSWORD}" \
  MAVEN_BIN="${RUNTIME}/maven/bin/mvn" \
  MAVEN_LOCAL_REPOSITORY="${RUNTIME}/m2" \
  JAVA_RESOURCES_DIR="${REPOSITORY_ROOT}/main/manager-api/src/main/resources" \
    "${SCRIPT_DIR}/run-migrations.sh"
}

migrate() {
  start
  migrate_one "${JAVA_DATABASE}"
  migrate_one "${FASTAPI_DATABASE}"
}

print_env() {
  cat <<EOF
export TEST_MYSQL_PORT='${MYSQL_PORT}'
export TEST_REDIS_PORT='${REDIS_PORT}'
export TEST_JAVA_DATABASE_URL='mysql+asyncmy://${TEST_USER}:${TEST_PASSWORD}@127.0.0.1:${MYSQL_PORT}/${JAVA_DATABASE}?charset=utf8mb4'
export TEST_FASTAPI_DATABASE_URL='mysql+asyncmy://${TEST_USER}:${TEST_PASSWORD}@127.0.0.1:${MYSQL_PORT}/${FASTAPI_DATABASE}?charset=utf8mb4'
export TEST_JAVA_JDBC_URL='jdbc:mysql://127.0.0.1:${MYSQL_PORT}/${JAVA_DATABASE}?useUnicode=true&characterEncoding=UTF-8&serverTimezone=Asia/Shanghai&allowMultiQueries=true'
export TEST_JAVA_REDIS_URL='redis://127.0.0.1:${REDIS_PORT}/1'
export TEST_FASTAPI_REDIS_URL='redis://127.0.0.1:${REDIS_PORT}/2'
EOF
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  reset) reset ;;
  migrate) migrate ;;
  env) print_env ;;
  *) echo "usage: $0 {start|stop|reset|migrate|env}" >&2; exit 2 ;;
esac
