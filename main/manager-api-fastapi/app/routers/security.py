# ruff: noqa: B008
# FastAPI evaluates dependency marker defaults intentionally when registering routes.
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.core.database import get_db
from app.core.errors import AppError
from app.core.responses import JavaJSONResponse, ok
from app.core.security import require_normal
from app.repositories.security import SecurityRepository
from app.schemas.security import (
    LoginRequest,
    PasswordChangeRequest,
    RetrievePasswordRequest,
    SmsVerificationRequest,
)
from app.services.security import CaptchaService, SecurityService

security_router = APIRouter()


def _service(session: AsyncSession) -> SecurityService:
    return SecurityService(SecurityRepository(session))


@security_router.get("/user/captcha")
async def captcha(uuid: str | None = Query(default=None)) -> Response:
    if uuid is None or not uuid.strip():
        raise AppError(10006)
    content = await CaptchaService().create(uuid)
    return Response(
        content,
        media_type="image/gif",
        headers={
            "Pragma": "No-cache",
            "Cache-Control": "no-cache",
            "Expires": "Thu, 01 Jan 1970 00:00:00 GMT",
        },
    )


@security_router.post("/user/smsVerification")
async def sms_verification(dto: SmsVerificationRequest, session: AsyncSession = Depends(get_db)) -> JavaJSONResponse:
    await _service(session).send_sms_verification(dto)
    return ok()


@security_router.post("/user/login")
async def login(
    dto: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    return ok(await _service(session).login(dto, request))


@security_router.post("/user/register")
async def register(dto: LoginRequest, session: AsyncSession = Depends(get_db)) -> JavaJSONResponse:
    await _service(session).register(dto)
    return ok()


@security_router.get("/user/info")
async def info(request: Request) -> JavaJSONResponse:
    user = require_normal(request)
    return ok(
        {
            "id": user.id,
            "username": user.username,
            "superAdmin": user.super_admin,
            "token": user.token,
            "status": user.status,
        }
    )


@security_router.put("/user/change-password")
async def change_password(
    dto: PasswordChangeRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    await _service(session).change_password(
        require_normal(request),
        dto,
        request.headers.get("Accept-Language"),
    )
    return ok()


@security_router.put("/user/retrieve-password")
async def retrieve_password(
    dto: RetrievePasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    await _service(session).retrieve_password(dto, request.headers.get("Accept-Language"))
    return ok()


@security_router.get("/user/pub-config")
async def public_config(session: AsyncSession = Depends(get_db)) -> JavaJSONResponse:
    return ok(await _service(session).public_config())


@security_router.get("/api/ping")
async def api_ping() -> JavaJSONResponse:
    return ok("pong")
