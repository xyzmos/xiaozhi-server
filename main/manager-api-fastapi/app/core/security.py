from __future__ import annotations

import fnmatch
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.errors import AppError, ErrorCode
from app.core.responses import error_response
from app.services.system_params import SystemParamService

PUBLIC_PATTERNS = (
    "/ota/*",
    "/ota",
    "/otaMag/download/*",
    "/webjars/*",
    "/druid/*",
    "/v3/api-docs*",
    "/doc.html*",
    "/favicon.ico",
    "/user/captcha",
    "/user/smsVerification",
    "/user/login",
    "/user/pub-config",
    "/user/register",
    "/user/retrieve-password",
    "/api/ping",
    "/agent/chat-history/download/*",
    "/agent/play/*",
    "/voiceClone/play/*",
    "/health",
    "/health/live",
    "/health/ready",
)
SERVER_PATTERNS = (
    "/config/*",
    "/device/address-book/call",
    "/device/address-book/lookup",
    "/agent/chat-history/report",
    "/agent/chat-summary/*",
    "/agent/chat-title/*",
)


@dataclass(slots=True, frozen=True)
class AuthUser:
    id: int
    username: str
    super_admin: int
    status: int
    token: str
    row: dict[str, Any]

    @property
    def is_super_admin(self) -> bool:
        return self.super_admin == 1


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        return None
    value = authorization[len("Bearer ") :]
    return value if value.strip() else None


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)
        settings = get_settings()
        path = request.url.path
        if settings.context_path and path.startswith(settings.context_path):
            path = path[len(settings.context_path) :] or "/"
        if _matches(path, PUBLIC_PATTERNS):
            request.state.auth_mode = "anonymous"
            return await call_next(request)
        if _matches(path, SERVER_PATTERNS):
            return await self._server_auth(request, call_next)
        return await self._user_auth(request, call_next)

    async def _server_auth(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        provided = _bearer_token(request)
        if provided is None:
            return error_response(
                request,
                ErrorCode.UNAUTHORIZED,
                "服务器密钥不能为空",
                media_type="application/json;charset=utf-8",
            )
        expected = get_settings().server_secret_override
        if expected is None:
            try:
                async with get_session_factory()() as session:
                    expected = await SystemParamService(session).get_value("server.secret", from_cache=True)
            except Exception:
                expected = None
        if not expected or not hmac.compare_digest(provided, expected):
            return error_response(
                request,
                ErrorCode.UNAUTHORIZED,
                "无效的服务器密钥",
                media_type="application/json;charset=utf-8",
            )
        request.state.auth_mode = "server"
        return await call_next(request)

    async def _user_auth(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        token = _bearer_token(request)
        if token is None:
            return error_response(
                request,
                ErrorCode.UNAUTHORIZED,
                media_type="application/json;charset=utf-8",
            )
        try:
            async with get_session_factory()() as session:
                result = await session.execute(
                    text(
                        "SELECT u.* FROM sys_user_token t "
                        "JOIN sys_user u ON u.id = t.user_id "
                        "WHERE t.token = :token AND t.expire_date >= CURRENT_TIMESTAMP LIMIT 1"
                    ),
                    {"token": token},
                )
                mapping = result.mappings().first()
        except Exception:
            mapping = None
        if mapping is None or mapping.get("status") is None or int(mapping["status"]) != 1:
            return error_response(
                request,
                ErrorCode.UNAUTHORIZED,
                media_type="application/json;charset=utf-8",
            )
        row = dict(mapping)
        request.state.user = AuthUser(
            id=int(row["id"]),
            username=str(row.get("username") or ""),
            super_admin=int(row.get("super_admin") or 0),
            status=int(row["status"]),
            token=token,
            row=row,
        )
        request.state.auth_mode = "user"
        return await call_next(request)


def current_user(request: Request) -> AuthUser:
    user = getattr(request.state, "user", None)
    if not isinstance(user, AuthUser):
        raise AppError(ErrorCode.UNAUTHORIZED)
    return user


def require_normal(request: Request) -> AuthUser:
    return current_user(request)


def require_super_admin(request: Request) -> AuthUser:
    user = current_user(request)
    if not user.is_super_admin:
        raise AppError(ErrorCode.FORBIDDEN)
    return user


def shanghai_now_naive() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(tz=ZoneInfo(get_settings().timezone)).replace(tzinfo=None)
