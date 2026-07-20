from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import configure_database, database_ping, dispose_database
from app.core.errors import AppError, ErrorCode
from app.core.i18n import message_for
from app.core.redis import close_redis, redis_ping
from app.core.responses import JavaJSONResponse, error_response, ok
from app.core.security import AuthenticationMiddleware
from app.routers import application_routers

logger = logging.getLogger(__name__)
settings = get_settings()

_MULTIPART_VALIDATION_PATHS = {
    "/datasets/{dataset_id}/documents",
    "/otaMag/upload",
    "/otaMag/uploadAssetsBin",
    "/voiceClone/upload",
}


def _matches_path_template(path: str, template: str) -> bool:
    path_parts = path.removeprefix(settings.context_path).strip("/").split("/")
    template_parts = template.strip("/").split("/")
    return len(path_parts) == len(template_parts) and all(
        expected.startswith("{") and expected.endswith("}") or actual == expected
        for actual, expected in zip(path_parts, template_parts, strict=True)
    )


def _java_required_message(request: Request, errors: Sequence[Mapping[str, Any]]) -> str | None:
    path = request.url.path.removeprefix(settings.context_path)
    mappings = (
        (
            "/admin/server/emit-action",
            (("action", "操作不能为空"), ("targetWs", "目标ws地址不能为空")),
        ),
        ("/agent", (("agentName", "智能体名称不能为空"),)),
        (
            "/agent/chat-history/report",
            tuple((field, "不能为空") for field in ("macAddress", "sessionId", "chatType", "content")),
        ),
        (
            "/agent/{agentId}/snapshots/{snapshotId}/restore",
            (("currentStateToken", "不能为空"),),
        ),
        (
            "/config/agent-models",
            (
                ("macAddress", "设备MAC地址不能为空"),
                ("clientId", "客户端ID不能为空"),
                ("selectedModule", "客户端已实例化的模型不能为空"),
            ),
        ),
        ("/config/correct-words", (("macAddress", "设备MAC地址不能为空"),)),
        (
            "/device/address-book/alias",
            (("targetMac", "目标MAC地址不能为空"), ("macAddress", "MAC地址不能为空")),
        ),
    )
    missing_fields: set[str] = set()
    for error in errors:
        location = tuple(error.get("loc", ()))
        if error.get("type") == "missing" and location[:1] == ("body",):
            missing_fields.add(str(location[-1]))
    if not missing_fields:
        return None
    for template, fields in mappings:
        if _matches_path_template(path, template):
            return next((message for field, message in fields if field in missing_fields), None)
    return None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    os.environ["TZ"] = settings.timezone
    if hasattr(time, "tzset"):
        time.tzset()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    configure_database(settings)
    if not settings.i18n_dir.exists():
        raise RuntimeError(f"Java i18n resources are missing: {settings.i18n_dir}")
    if not settings.changelog_path.exists():
        raise RuntimeError(f"Liquibase source of truth is missing: {settings.changelog_path}")
    if not settings.allow_start_without_dependencies:
        if not await database_ping():
            raise RuntimeError("database readiness check failed")
        if not await redis_ping():
            raise RuntimeError("Redis readiness check failed")
    yield
    await close_redis()
    await dispose_database()


app = FastAPI(
    title="xiaozhi-manager-api",
    version="0.1.0",
    docs_url=f"{settings.context_path}/doc.html",
    openapi_url=f"{settings.context_path}/v3/api-docs",
    redoc_url=None,
    default_response_class=JavaJSONResponse,
    lifespan=lifespan,
)

app.add_middleware(AuthenticationMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    max_age=3600,
)

for router in application_routers():
    app.include_router(router, prefix=settings.context_path)


@app.get(f"{settings.context_path}/health", include_in_schema=False)
async def health() -> JavaJSONResponse:
    return ok({"status": "UP"})


@app.get(f"{settings.context_path}/health/live", include_in_schema=False)
async def liveness() -> JavaJSONResponse:
    return ok({"status": "UP"})


def upload_storage_ready() -> bool:
    """Report whether the non-root API process can traverse and write its upload mount."""

    try:
        return settings.upload_dir.is_dir() and os.access(
            settings.upload_dir,
            os.W_OK | os.X_OK,
        )
    except OSError:
        return False


@app.get(f"{settings.context_path}/health/ready", include_in_schema=False)
async def readiness() -> JavaJSONResponse:
    database, redis, uploads = await database_ping(), await redis_ping(), upload_storage_ready()
    code = 0 if database and redis and uploads else 503
    msg = "success" if code == 0 else "dependencies unavailable"
    return JavaJSONResponse(
        {
            "code": code,
            "msg": msg,
            "data": {"database": database, "redis": redis, "uploads": uploads},
        },
        status_code=200 if code == 0 else 503,
    )


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JavaJSONResponse:
    return error_response(request, exc.code, exc.message, params=exc.params)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JavaJSONResponse:
    errors = exc.errors()
    # Spring only maps MethodArgumentNotValidException (a deserialized JSON
    # object's @Valid field constraints) to code 10034.  Root-body conversion,
    # missing query parameters and multipart binding failures reach its generic
    # exception handler and therefore keep the HTTP-200/code-500 envelope.
    root_body_error = any(tuple(error.get("loc", ())) == ("body",) for error in errors)
    missing_query = any(
        error.get("type") == "missing" and tuple(error.get("loc", ()))[:1] == ("query",)
        for error in errors
    )
    multipart_binding_error = any(
        error.get("type") == "missing"
        and tuple(error.get("loc", ()))[:1] == ("body",)
        and any(_matches_path_template(request.url.path, path) for path in _MULTIPART_VALIDATION_PATHS)
        for error in errors
    )
    if root_body_error or missing_query or multipart_binding_error:
        return error_response(request, ErrorCode.INTERNAL_SERVER_ERROR)
    first = errors[0] if errors else None
    detail = _java_required_message(request, errors) or (str(first.get("msg")) if first else None)
    return error_response(request, ErrorCode.PARAM_VALUE_NULL, detail)


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, _: IntegrityError) -> JavaJSONResponse:
    return error_response(request, ErrorCode.DB_RECORD_EXISTS)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JavaJSONResponse:
    if exc.status_code == 404:
        not_found = message_for(ErrorCode.RESOURCE_NOT_FOUND, request.headers.get("Accept-Language"))
        return error_response(request, 404, not_found)
    return error_response(request, exc.status_code, str(exc.detail))


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JavaJSONResponse:
    logger.exception("Unhandled manager-api error", exc_info=exc)
    return error_response(request, ErrorCode.INTERNAL_SERVER_ERROR)
