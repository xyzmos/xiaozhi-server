FROM python:3.10.20-bookworm AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120 \
    UV_HTTP_RETRIES=10 \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/

COPY main/manager-api-fastapi/pyproject.toml main/manager-api-fastapi/uv.lock main/manager-api-fastapi/README.md ./
COPY main/manager-api-fastapi/app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.10.20-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    APP_JAVA_RESOURCES_DIR=/opt/xiaozhi/java-resources \
    APP_UPLOAD_DIR=/data/uploads \
    APP_HOST=0.0.0.0 \
    APP_PORT=8002 \
    APP_TIMEZONE=Asia/Shanghai

WORKDIR /app

RUN groupadd --gid 10001 xiaozhi \
    && useradd --uid 10001 --gid xiaozhi --create-home --shell /usr/sbin/nologin xiaozhi

COPY --from=build --chown=10001:10001 /app/.venv ./.venv
COPY --from=build --chown=10001:10001 /app/app ./app

COPY main/manager-api-fastapi/scripts/container-entrypoint.sh /usr/local/bin/manager-api-entrypoint
COPY main/manager-api/src/main/resources/i18n /opt/xiaozhi/java-resources/i18n
COPY main/manager-api/src/main/resources/db /opt/xiaozhi/java-resources/db

RUN mkdir -p /data/uploads \
    && ln -s /data/uploads /app/uploadfile \
    && chown -R xiaozhi:xiaozhi /data/uploads /opt/xiaozhi \
    && chmod 0555 /usr/local/bin/manager-api-entrypoint

USER 10001:10001
EXPOSE 8002
VOLUME ["/data/uploads"]
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=4 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8002/xiaozhi/health/live', timeout=2).read()"]

ENTRYPOINT ["/usr/local/bin/manager-api-entrypoint"]
