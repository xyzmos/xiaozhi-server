from __future__ import annotations

import json
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import Request
from sqlalchemy import text

from app.core.crypto import bcrypt_hash, sm2_encrypt_c1c3c2
from app.core.errors import AppError
from app.core.redis import JavaRedisCodec
from app.core.security import AuthUser
from app.repositories.security import SecurityRepository
from app.routers.security import security_router
from app.schemas.security import (
    LoginRequest,
    PasswordChangeRequest,
    RetrievePasswordRequest,
    SmsVerificationRequest,
)
from app.services.security import AliyunSmsSender, CaptchaService, SecurityService
from tests.domain_support import FakeRedis, sqlite_session

SECURITY_SCHEMA = [
    "CREATE TABLE sys_params (param_code TEXT PRIMARY KEY, param_value TEXT)",
    "CREATE TABLE sys_user ("
    "id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, super_admin INTEGER, status INTEGER, "
    "creator INTEGER, create_date DATETIME, updater INTEGER, update_date DATETIME)",
    "CREATE TABLE sys_user_token ("
    "id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, token TEXT, expire_date DATETIME, "
    "update_date DATETIME, create_date DATETIME)",
    "CREATE TABLE sys_dict_type (id INTEGER PRIMARY KEY, dict_type TEXT)",
    "CREATE TABLE sys_dict_data ("
    "id INTEGER PRIMARY KEY, dict_type_id INTEGER, dict_label TEXT, dict_value TEXT, sort INTEGER)",
]
SM2_VECTOR = json.loads((Path(__file__).parent / "fixtures" / "sm2-c1c3c2-golden.json").read_text(encoding="utf-8"))


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/xiaozhi/user/login",
            "headers": [(b"user-agent", b"Manager-Web"), (b"x-forwarded-for", b"192.0.2.10")],
            "client": ("127.0.0.1", 52341),
        }
    )


@pytest.mark.asyncio
async def test_sm2_login_reuses_token_and_password_change_expires_it() -> None:
    public_key, private_key = SM2_VECTOR["publicKey"], SM2_VECTOR["privateKey"]
    redis = FakeRedis()
    async with sqlite_session(SECURITY_SCHEMA) as session:
        await session.execute(
            text("INSERT INTO sys_params VALUES ('server.private_key', :private_key)"),
            {"private_key": private_key},
        )
        await session.execute(
            text(
                "INSERT INTO sys_user "
                "(id, username, password, super_admin, status) VALUES (1, 'alice', :password, 1, 1)"
            ),
            {"password": bcrypt_hash("StrongPass1", rounds=4)},
        )
        await session.commit()

        captcha = CaptchaService(redis)  # type: ignore[arg-type]
        service = SecurityService(
            SecurityRepository(session),
            redis=redis,  # type: ignore[arg-type]
            captcha=captcha,
        )
        await redis.set("sys:captcha:first", JavaRedisCodec.encode("Ab12C"), ex=300)
        first = await service.login(
            LoginRequest(
                username="alice",
                password=sm2_encrypt_c1c3c2(public_key, "Ab12CStrongPass1"),
                captcha_id="first",
            ),
            _request(),
        )
        assert len(first["token"]) == 32
        assert len(first["clientHash"]) == 32
        assert await redis.get("sys:captcha:first") is None

        await redis.set("sys:captcha:second", JavaRedisCodec.encode("Z9x8Y"), ex=300)
        second = await service.login(
            LoginRequest(
                username="alice",
                password=sm2_encrypt_c1c3c2(public_key, "Z9x8YStrongPass1"),
                captcha_id="second",
            ),
            _request(),
        )
        assert second["token"] == first["token"]

        auth = AuthUser(1, "alice", 1, 1, first["token"], {})
        await service.change_password(
            auth,
            PasswordChangeRequest(password="StrongPass1", new_password="NewStrong2"),  # noqa: S106
        )
        expiry = await session.scalar(text("SELECT expire_date FROM sys_user_token WHERE user_id = 1"))
        assert expiry is not None
        parsed_expiry = datetime.fromisoformat(expiry) if isinstance(expiry, str) else expiry
        assert parsed_expiry < datetime.now()

        await redis.set("sys:captcha:bad", JavaRedisCodec.encode("right"), ex=300)
        with pytest.raises(AppError) as captured:
            await service.login(
                LoginRequest(
                    username="alice",
                    password=sm2_encrypt_c1c3c2(public_key, "wrongNewStrong2"),
                    captcha_id="bad",
                ),
                _request(),
            )
        assert captured.value.code == 10067
        assert await redis.get("sys:captcha:bad") is None

        with pytest.raises(AppError) as missing_password:
            await service.login(LoginRequest(username="alice"), _request())
        assert missing_password.value.code == 10130

        with pytest.raises(AppError) as manual_validation:
            await service.change_password(auth, PasswordChangeRequest(), "en-US")
        assert manual_validation.value.code == 500
        assert manual_validation.value.message == "The password cannot be empty"

        await session.execute(
            text(
                "INSERT INTO sys_params VALUES "
                "('server.enable_mobile_register', 'true'), ('server.public_key', 'unused')"
            )
        )
        await session.commit()
        with pytest.raises(AppError) as retrieve_validation:
            await service.retrieve_password(RetrievePasswordRequest(), "de-DE")
        assert retrieve_validation.value.code == 500
        assert retrieve_validation.value.message == "Das Passwort darf nicht leer sein"


class _RecordingSmsSender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def send_verification_code(self, phone: str | None, code: str) -> None:
        assert phone is not None
        self.calls.append((phone, code))


@pytest.mark.asyncio
async def test_sms_rate_limit_cache_ttl_and_aliyun_rpc_shape() -> None:
    redis = FakeRedis()
    sender = _RecordingSmsSender()
    async with sqlite_session(SECURITY_SCHEMA) as session:
        await session.execute(
            text(
                "INSERT INTO sys_params VALUES "
                "('server.enable_mobile_register', 'true'),"
                "('server.sms_max_send_count', '2'),"
                "('aliyun.sms.access_key_id', 'test-id'),"
                "('aliyun.sms.access_key_secret', 'test-secret'),"
                "('aliyun.sms.sign_name', 'test-sign'),"
                "('aliyun.sms.sms_code_template_code', 'SMS_123')"
            )
        )
        await session.commit()
        await redis.set("sys:captcha:sms-flow", JavaRedisCodec.encode("A1b2C"), ex=300)
        service = SecurityService(
            SecurityRepository(session),
            redis=redis,  # type: ignore[arg-type]
            captcha=CaptchaService(redis),  # type: ignore[arg-type]
            sms_sender=sender,
        )
        with pytest.raises(AppError) as missing_sms_fields:
            await service.send_sms_verification(SmsVerificationRequest())
        assert missing_sms_fields.value.code == 10067

        dto = SmsVerificationRequest(phone="+8613800138000", captcha="a1B2c", captcha_id="sms-flow")
        await service.send_sms_verification(dto)

        assert len(sender.calls) == 1
        assert sender.calls[0][0] == "+8613800138000"
        assert sender.calls[0][1].isdigit() and len(sender.calls[0][1]) == 6
        cached_code = JavaRedisCodec.decode(await redis.get("sys:captcha:sms:Validate:Code:+8613800138000"))
        assert cached_code == sender.calls[0][1]
        assert 0 < await redis.ttl("sms:Validate:Code:+8613800138000:today_count") <= 86400

        with pytest.raises(AppError) as captured:
            await service.send_sms_verification(dto)
        assert captured.value.code == 10060

        recorded: dict[str, Any] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            recorded["params"] = dict(urllib.parse.parse_qsl((await request.aread()).decode()))
            return httpx.Response(200, json={"Code": "OK"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            aliyun = AliyunSmsSender(
                SecurityRepository(session),
                redis=redis,  # type: ignore[arg-type]
                client=client,
            )
            await aliyun.send_verification_code("+8613800138000", "123456")
        params = recorded["params"]
        assert params["Action"] == "SendSms"
        assert params["TemplateParam"] == '{"code":"123456"}'
        assert params["Signature"]

        await session.execute(
            text(
                "UPDATE sys_params SET param_value = '' "
                "WHERE param_code IN ('aliyun.sms.access_key_id', 'aliyun.sms.access_key_secret')"
            )
        )
        await session.commit()
        blank_credentials = AliyunSmsSender(
            SecurityRepository(session),
            redis=FakeRedis(),  # type: ignore[arg-type]
        )
        with pytest.raises(AppError) as connection_error:
            await blank_credentials.send_verification_code("+8613800138000", "123456")
        assert connection_error.value.code == 10056


def test_security_router_exposes_all_login_controller_routes_and_ping() -> None:
    routes = {(next(iter(route.methods)), route.path) for route in security_router.routes}
    assert len(routes) == 9
    assert ("POST", "/user/login") in routes
    assert ("GET", "/user/captcha") in routes
    assert ("GET", "/api/ping") in routes
