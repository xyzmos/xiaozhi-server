#!/bin/sh
set -eu

: "${LIQUIBASE_URL:?Set LIQUIBASE_URL to the isolated or deployment JDBC URL}"
: "${LIQUIBASE_USERNAME:?Set LIQUIBASE_USERNAME}"
: "${LIQUIBASE_PASSWORD:?Set LIQUIBASE_PASSWORD}"

JDBC_URL=${LIQUIBASE_URL}
JDBC_USERNAME=${LIQUIBASE_USERNAME}
JDBC_PASSWORD=${LIQUIBASE_PASSWORD}
unset LIQUIBASE_URL LIQUIBASE_USERNAME LIQUIBASE_PASSWORD
export MIGRATION_JDBC_URL=${JDBC_URL}
export MIGRATION_USERNAME=${JDBC_USERNAME}
export MIGRATION_PASSWORD=${JDBC_PASSWORD}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
POM="${MIGRATION_POM:-${PROJECT_DIR}/migration-pom.xml}"
JAVA_RESOURCES="${JAVA_RESOURCES_DIR:-${PROJECT_DIR}/../manager-api/src/main/resources}"
if [ -n "${MIGRATION_RUNNER_JAR:-}" ]; then
  exec java -jar "${MIGRATION_RUNNER_JAR}"
fi

RUNTIME_ROOT="${PROJECT_DIR}/../../.runtime"
if [ -n "${MAVEN_BIN:-}" ]; then
  MAVEN="${MAVEN_BIN}"
elif [ -x "${RUNTIME_ROOT}/maven/bin/mvn" ]; then
  MAVEN="${RUNTIME_ROOT}/maven/bin/mvn"
else
  MAVEN="mvn"
fi

MAVEN_REPOSITORY_ARGS=""
if [ -n "${MAVEN_LOCAL_REPOSITORY:-}" ]; then
  MAVEN_REPOSITORY_ARGS="-Dmaven.repo.local=${MAVEN_LOCAL_REPOSITORY}"
elif [ -x "${RUNTIME_ROOT}/maven/bin/mvn" ]; then
  MAVEN_REPOSITORY_ARGS="-Dmaven.repo.local=${RUNTIME_ROOT}/m2"
fi

"${MAVEN}" -B -f "${POM}" ${MAVEN_REPOSITORY_ARGS} \
  -Djava.resources.dir="${JAVA_RESOURCES}" package
if [ -n "${JAVA_BIN:-}" ]; then
  JAVA="${JAVA_BIN}"
elif [ -n "${JAVA_HOME:-}" ] && [ -x "${JAVA_HOME}/bin/java" ]; then
  JAVA="${JAVA_HOME}/bin/java"
elif [ -x "${RUNTIME_ROOT}/jdk/bin/java" ]; then
  JAVA="${RUNTIME_ROOT}/jdk/bin/java"
else
  JAVA="java"
fi
exec "${JAVA}" -jar "${PROJECT_DIR}/target/manager-api-liquibase-runner-1.0.0-all.jar"
