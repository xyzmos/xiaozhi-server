# manager-api-fastapi

`manager-api-fastapi` is the Python/FastAPI implementation of the existing Spring Boot
`main/manager-api`. The Java service remains in the repository as the contract baseline,
Liquibase migration owner, and rollback implementation.

## Local development

The service requires Python 3.10, MySQL 8, and Redis 5 or newer. Never point tests at a
development database: the integration harness creates a dedicated database and Redis
namespace/instance.

```bash
cd main/manager-api-fastapi
cp .env.example .env
uv sync --locked
uv run python -m app
```

The compatible base URL is `http://127.0.0.1:8002/xiaozhi`. OpenAPI is exposed at
`/xiaozhi/v3/api-docs` and the Swagger UI at `/xiaozhi/doc.html`.

Production must set `APP_DATABASE_URL`, `APP_REDIS_URL`, `APP_UPLOAD_DIR`, and
`APP_JAVA_RESOURCES_DIR`. The last path must contain the original Java i18n resources and
Liquibase changelog. `APP_SERVER_SECRET_OVERRIDE` is reserved for isolated tests; leaving it
set in a deployment bypasses the database-backed `server.secret` lookup and is unsupported.

## Commands

```bash
uv run pytest
uv run ruff check app tests scripts
uv run mypy app
uv run python scripts/extract_java_routes.py --output compatibility/java-routes.json
```

Migration, container, differential-contract, and cutover instructions are maintained in the
repository-level migration documents under `docs/manager-api-fastapi-*.md`.

The cross-module plan for integrating manager-web and the xiaozhi-server realtime runtime is
maintained in `docs/unified-fastapi-platform/README.md`. It defines the staged PR queue, agent
ownership, automated quality gates, and the boundary where real hardware and external service
validation become mandatory.
