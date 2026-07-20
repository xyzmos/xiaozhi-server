from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_dependency_versions_are_explicitly_locked() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert '"fastapi==0.116.1"' in project
    assert '"pydantic==2.11.7"' in project
    assert '"uvicorn[standard]==0.35.0"' in project
    assert 'name = "pydantic"\nversion = "2.11.7"' in lock


def test_container_artifacts_are_pinned_and_preserve_the_java_upload_path() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    migration_dockerfile = (ROOT / "Dockerfile.migrations").read_text(encoding="utf-8")
    migration_pom = (ROOT / "migration-pom.xml").read_text(encoding="utf-8")
    assert dockerfile.startswith("FROM python:3.10.20-bookworm AS build\n")
    assert dockerfile.count("FROM python:3.10.20-slim-bookworm") == 1
    assert "COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/" in dockerfile
    assert "UV_HTTP_TIMEOUT=120" in dockerfile
    assert "UV_HTTP_RETRIES=10" in dockerfile
    assert "apt-get" not in dockerfile
    assert "COPY --from=build --chown=10001:10001 /app/.venv ./.venv" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "ln -s /data/uploads /app/uploadfile" in dockerfile
    assert 'STOPSIGNAL SIGTERM' in dockerfile
    assert "FROM maven:3.9.9-eclipse-temurin-21 AS build" in migration_dockerfile
    assert "FROM eclipse-temurin:21-jre" in migration_dockerfile
    assert "--mount=type=cache,target=/root/.m2/repository" in migration_dockerfile
    assert "-Daether.connector.basic.threads=1" in migration_dockerfile
    assert "-Daether.connector.connectTimeout=15000" in migration_dockerfile
    assert "-Daether.connector.requestTimeout=60000" in migration_dockerfile
    assert "-Daether.connector.http.retryHandler.count=5" in migration_dockerfile
    assert "USER 10001:10001" in migration_dockerfile
    assert "STOPSIGNAL SIGTERM" in migration_dockerfile
    assert "manager-api-liquibase-runner-1.0.0-all.jar" in migration_dockerfile
    assert "<shadedArtifactAttached>true</shadedArtifactAttached>" in migration_pom
    assert "<shadedClassifierName>all</shadedClassifierName>" in migration_pom
    assert ":latest" not in dockerfile + migration_dockerfile


def test_compose_separates_migrations_api_jobs_and_nginx() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert set(services) == {
        "manager-api-migrate",
        "manager-api-fastapi",
        "manager-api-jobs",
        "manager-api-nginx",
    }
    api = services["manager-api-fastapi"]
    jobs = services["manager-api-jobs"]
    assert api["depends_on"]["manager-api-migrate"]["condition"] == "service_completed_successfully"
    assert jobs["command"] == ["python", "-m", "app.jobs.worker"]
    assert api["read_only"] is True and jobs["read_only"] is True
    assert api["stop_grace_period"] == "40s"
    expected_upload = ["${MANAGER_API_UPLOAD_SOURCE:-manager-api-uploads}:/data/uploads"]
    assert api["volumes"] == jobs["volumes"] == expected_upload
    assert api["environment"]["APP_GRACEFUL_SHUTDOWN_SECONDS"] == "${APP_GRACEFUL_SHUTDOWN_SECONDS:-30}"
    assert jobs["environment"]["APP_GRACEFUL_SHUTDOWN_SECONDS"] == "${APP_GRACEFUL_SHUTDOWN_SECONDS:-30}"


def test_nginx_health_and_startup_scripts_are_wired() -> None:
    nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
    nginx_dockerfile = (ROOT / "Dockerfile.nginx").read_text(encoding="utf-8")
    nginx_entrypoint = ROOT / "deploy" / "nginx-entrypoint.sh"
    compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    compose = yaml.safe_load(compose_text)
    nginx_service = compose["services"]["manager-api-nginx"]
    assert "location /xiaozhi/" in nginx
    assert "location = /xiaozhi" in nginx
    assert "server ${MANAGER_API_UPSTREAM};" in nginx
    assert "proxy_request_buffering off;" in nginx
    assert "proxy_buffering off;" in nginx
    assert "client_max_body_size 100m;" in nginx
    assert nginx_dockerfile.startswith("FROM nginx:1.28.0-alpine\n")
    assert ":latest" not in nginx_dockerfile
    assert "envsubst '${MANAGER_API_UPSTREAM}'" in nginx_dockerfile
    assert nginx_service["build"]["dockerfile"] == "main/manager-api-fastapi/Dockerfile.nginx"
    assert nginx_service["environment"] == {
        "MANAGER_API_UPSTREAM": "${MANAGER_API_UPSTREAM:-manager-api-fastapi:8002}"
    }
    assert nginx_service["read_only"] is True
    assert set(nginx_service["tmpfs"]) == {
        "/var/cache/nginx:size=32m",
        "/var/run:size=1m",
        "/tmp:size=16m",  # noqa: S108 - literal deployment mount, not a test scratch path
    }
    assert nginx_service["depends_on"]["manager-api-fastapi"]["condition"] == "service_healthy"
    assert "/xiaozhi/health/ready" in compose_text
    assert os.access(nginx_entrypoint, os.X_OK)
    syntax = subprocess.run(  # noqa: S603
        ["/bin/sh", "-n", str(nginx_entrypoint)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert syntax.returncode == 0, syntax.stderr
    for script_name in (
        "container-entrypoint.sh",
        "run-migrations.sh",
        "isolated-env.sh",
        "start-api.sh",
        "start-jobs.sh",
    ):
        script = ROOT / "scripts" / script_name
        assert script.read_text(encoding="utf-8").startswith("#!/bin/sh\nset -eu\n")
        assert os.access(script, os.X_OK), f"{script_name} must be executable"


def test_docker_context_excludes_local_runtimes_secrets_and_build_products() -> None:
    dockerignore = (ROOT.parents[1] / ".dockerignore").read_text(encoding="utf-8")
    for ignored in (
        ".env",
        ".runtime/",
        ".venv-*/",
        "**/.venv/",
        "**/.test-runtime/",
        "**/node_modules/",
        "**/dist/",
        "**/target/",
        "**/uploadfile/",
        "main/xiaozhi-server/models/",
        "main/xiaozhi-server/data/",
    ):
        assert ignored in dockerignore


def test_start_scripts_are_executable_without_shell_reinterpretation() -> None:
    environment = {**os.environ, "PYTHON_BIN": "/bin/echo"}
    api = subprocess.run(  # noqa: S603
        [str(ROOT / "scripts" / "start-api.sh")],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert "-m uvicorn app.main:app" in api.stdout
    assert "--timeout-graceful-shutdown 30" in api.stdout
    jobs = subprocess.run(  # noqa: S603
        [str(ROOT / "scripts" / "start-jobs.sh")],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert jobs.stdout.strip() == "-m app.jobs.worker"
    override = subprocess.run(  # noqa: S603
        [str(ROOT / "scripts" / "container-entrypoint.sh"), "/bin/echo", "override-ok"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert override.stdout.strip() == "override-ok"


def test_repository_local_restart_entrypoint_keeps_fastapi_default_and_java_rollback() -> None:
    restart = ROOT.parents[1] / "scripts" / "restart-local-services.sh"
    assert os.access(restart, os.X_OK)
    syntax = subprocess.run(  # noqa: S603
        ["/bin/sh", "-n", str(restart)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert syntax.returncode == 0, syntax.stderr
    help_result = subprocess.run(  # noqa: S603
        [str(restart), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--manager-api fastapi|java" in help_result.stdout
    assert "The FastAPI manager is the default" in help_result.stdout


def test_local_migration_script_prefers_bundled_jdk_maven_and_repository() -> None:
    script = (ROOT / "scripts" / "run-migrations.sh").read_text(encoding="utf-8")
    assert 'RUNTIME_ROOT="${PROJECT_DIR}/../../.runtime"' in script
    assert 'MAVEN="${RUNTIME_ROOT}/maven/bin/mvn"' in script
    assert 'MAVEN_REPOSITORY_ARGS="-Dmaven.repo.local=${RUNTIME_ROOT}/m2"' in script
    assert 'JAVA="${RUNTIME_ROOT}/jdk/bin/java"' in script
    assert " clean package" not in script
    assert "manager-api-liquibase-runner-1.0.0-all.jar" in script
