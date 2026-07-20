from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import logging
import re
import secrets
import string
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta
from typing import Any, Protocol, cast

import httpx
from fastapi import Request
from PIL import Image, ImageDraw, ImageFont
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.crypto import bcrypt_hash, bcrypt_matches, generate_database_token, sm2_decrypt_c1c3c2
from app.core.errors import AppError, ErrorCode
from app.core.ids import snowflake
from app.core.redis import JavaRedisCodec, get_redis
from app.core.security import AuthUser, shanghai_now_naive
from app.repositories.security import SecurityRepository
from app.schemas.security import (
    LoginRequest,
    PasswordChangeRequest,
    RetrievePasswordRequest,
    SmsVerificationRequest,
)
from app.services.java_validation import validation_message

logger = logging.getLogger(__name__)

TOKEN_EXPIRE_SECONDS = 12 * 60 * 60
CAPTCHA_TTL_SECONDS = 5 * 60
CAPTCHA_LENGTH = 5
PHONE_PATTERN = re.compile(r"^\+[1-9]\d{0,3}[1-9]\d{4,14}$")
STRONG_PASSWORD = re.compile(r"^(?=.*[0-9])(?=.*[a-z])(?=.*[A-Z]).+$")


class SmsSender(Protocol):
    async def send_verification_code(self, phone: str | None, code: str) -> None: ...


class AliyunSmsSender:
    """Minimal implementation of the Aliyun Dysmsapi RPC request used by the Java SDK."""

    def __init__(
        self,
        repository: SecurityRepository,
        *,
        redis: Redis | None = None,
        client: httpx.AsyncClient | None = None,
        endpoint: str = "https://dysmsapi.aliyuncs.com/",
    ):
        self.repository = repository
        self.redis = redis or get_redis()
        self.client = client
        self.endpoint = endpoint

    async def send_verification_code(self, phone: str | None, code: str) -> None:
        access_key_id = await self._param("aliyun.sms.access_key_id") or ""
        access_key_secret = await self._param("aliyun.sms.access_key_secret") or ""
        sign_name = await self._param("aliyun.sms.sign_name") or ""
        template_code = await self._param("aliyun.sms.sms_code_template_code") or ""
        # The Tea SDK constructs its client before the refundable send block;
        # blank credentials therefore map to SMS_CONNECTION_FAILED (10056).
        if not access_key_id.strip() or not access_key_secret.strip():
            raise AppError(10056)
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        params: dict[str, str] = {
            "AccessKeyId": access_key_id,
            "Action": "SendSms",
            "Format": "JSON",
            "RegionId": "cn-hangzhou",
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": str(uuid.uuid4()),
            "SignatureVersion": "1.0",
            "SignName": sign_name,
            "TemplateCode": template_code,
            "TemplateParam": json.dumps({"code": code}, ensure_ascii=False, separators=(",", ":")),
            "Timestamp": timestamp,
            "Version": "2017-05-25",
        }
        if phone is not None:
            params["PhoneNumbers"] = phone
        params["Signature"] = self._signature(params, access_key_secret)
        if self.client is not None:
            response = await self.client.post(self.endpoint, data=params)
            response.raise_for_status()
            return
        timeout = get_settings().external_request_timeout_seconds
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(self.endpoint, data=params)
            response.raise_for_status()

    async def _param(self, code: str) -> str | None:
        cached = JavaRedisCodec.decode(await cast(Any, self.redis.hget)("sys:params", code))
        if cached is not None:
            return str(cached)
        value = await self.repository.get_param_value(code)
        if value is not None:
            await cast(Any, self.redis.hset)("sys:params", code, JavaRedisCodec.encode(value))
            await cast(Any, self.redis.expire)("sys:params", 24 * 60 * 60)
        return value

    @classmethod
    def _signature(cls, params: dict[str, str], secret: str) -> str:
        canonical = "&".join(
            f"{cls._percent_encode(key)}={cls._percent_encode(value)}" for key, value in sorted(params.items())
        )
        string_to_sign = f"POST&%2F&{cls._percent_encode(canonical)}"
        digest = hmac.new(
            f"{secret}&".encode(),
            string_to_sign.encode(),
            digestmod=hashlib.sha1,  # noqa: S324 - mandated by Aliyun RPC SignatureMethod
        ).digest()
        return base64.b64encode(digest).decode("ascii")

    @staticmethod
    def _percent_encode(value: str) -> str:
        return urllib.parse.quote(str(value), safe="~")


class CaptchaService:
    def __init__(self, redis: Redis | None = None):
        self.redis = redis or get_redis()

    async def create(self, identifier: str) -> bytes:
        code = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(CAPTCHA_LENGTH))
        await self._set_cache(identifier, code)
        return self._render_gif(code)

    async def validate(self, identifier: str | None, code: str | None, *, delete: bool) -> bool:
        if not code or not code.strip():
            return False
        key = self._captcha_key(identifier)
        cached = JavaRedisCodec.decode(await cast(Any, self.redis.get(key)))
        if cached is not None and delete:
            await cast(Any, self.redis.delete(key))
        return cached is not None and code.casefold() == str(cached).casefold()

    async def set_sms_code(self, phone: str | None, code: str) -> None:
        await self._set_cache(f"sms:Validate:Code:{phone}", code)

    async def validate_sms_code(self, phone: str | None, code: str | None, *, delete: bool = False) -> bool:
        return await self.validate(f"sms:Validate:Code:{phone}", code, delete=delete)

    async def _set_cache(self, identifier: str, value: str) -> None:
        await cast(Any, self.redis.set)(
            self._captcha_key(identifier),
            JavaRedisCodec.encode(value),
            ex=CAPTCHA_TTL_SECONDS,
        )

    @staticmethod
    def _captcha_key(identifier: str | None) -> str:
        return f"sys:captcha:{'null' if identifier is None else identifier}"

    @staticmethod
    def _render_gif(code: str) -> bytes:
        image = Image.new("RGB", (150, 40), (248, 248, 248))
        draw = ImageDraw.Draw(image)
        for _ in range(8):
            color = tuple(secrets.randbelow(150) for _ in range(3))
            draw.line(
                (
                    secrets.randbelow(150),
                    secrets.randbelow(40),
                    secrets.randbelow(150),
                    secrets.randbelow(40),
                ),
                fill=color,
                width=1,
            )
        font = ImageFont.load_default(size=24)
        for index, character in enumerate(code):
            color = tuple(secrets.randbelow(120) for _ in range(3))
            draw.text((10 + index * 27, 6 + secrets.randbelow(5)), character, font=font, fill=color)
        output = io.BytesIO()
        image.save(output, format="GIF")
        return output.getvalue()


class SecurityService:
    def __init__(
        self,
        repository: SecurityRepository,
        *,
        redis: Redis | None = None,
        captcha: CaptchaService | None = None,
        sms_sender: SmsSender | None = None,
    ):
        self.repository = repository
        self.redis = redis or get_redis()
        self.captcha = captcha or CaptchaService(self.redis)
        self.sms_sender = sms_sender or AliyunSmsSender(repository, redis=self.redis)

    async def login(self, dto: LoginRequest, request: Request) -> dict[str, Any]:
        password = await self._decrypt_and_validate_captcha(dto.password, dto.captcha_id)
        user = await self.repository.get_user_by_username(dto.username)
        if user is None or not bcrypt_matches(password, cast(str | None, user.get("password"))):
            raise AppError(ErrorCode.ACCOUNT_PASSWORD_ERROR)
        token = await self._create_token(int(user["id"]))
        await self.repository.session.commit()
        return {
            "token": token,
            "expire": TOKEN_EXPIRE_SECONDS,
            "clientHash": self._client_hash(request),
        }

    async def register(self, dto: LoginRequest) -> None:
        if not await self.allow_user_register():
            raise AppError(10072)
        password = await self._decrypt_and_validate_captcha(dto.password, dto.captcha_id)
        if await self._mobile_registration_enabled():
            if dto.username is None or not PHONE_PATTERN.fullmatch(dto.username):
                raise AppError(10069)
            if not await self.captcha.validate_sms_code(dto.username, dto.mobile_captcha, delete=False):
                raise AppError(10075)
        if await self.repository.get_user_by_username(dto.username) is not None:
            raise AppError(10070)
        if not STRONG_PASSWORD.fullmatch(password):
            raise AppError(ErrorCode.PASSWORD_WEAK_ERROR)
        now = shanghai_now_naive()
        user_count = await self.repository.count_users()
        await self.repository.insert_user(
            user_id=snowflake.next_id(),
            username=dto.username,
            password=bcrypt_hash(password),
            super_admin=1 if user_count == 0 else 0,
            now=now,
        )
        await self.repository.session.commit()

    async def change_password(
        self,
        user: AuthUser,
        dto: PasswordChangeRequest,
        accept_language: str | None = None,
    ) -> None:
        self._require_not_blank(dto.password, "sysuser.password.require", accept_language)
        self._require_not_blank(dto.new_password, "sysuser.password.require", accept_language)
        assert dto.password is not None
        assert dto.new_password is not None
        row = await self.repository.get_user_by_id(user.id)
        if row is None:
            raise AppError(ErrorCode.TOKEN_INVALID)
        if not bcrypt_matches(dto.password, cast(str | None, row.get("password"))):
            raise AppError(10048)
        if not STRONG_PASSWORD.fullmatch(dto.new_password):
            raise AppError(ErrorCode.PASSWORD_WEAK_ERROR)
        now = shanghai_now_naive()
        await self.repository.update_password(
            user.id,
            bcrypt_hash(dto.new_password),
            now,
            preserve_audit_fields=True,
        )
        # SysUserService.changePassword commits before the non-transactional token service logs out.
        await self.repository.session.commit()
        await self.repository.expire_user_token(user.id, now - timedelta(minutes=1))
        await self.repository.session.commit()

    async def retrieve_password(
        self,
        dto: RetrievePasswordRequest,
        accept_language: str | None = None,
    ) -> None:
        if not await self._mobile_registration_enabled():
            raise AppError(10073)
        self._require_not_blank(dto.phone, "sysuser.password.require", accept_language)
        self._require_not_blank(dto.code, "sysuser.password.require", accept_language)
        self._require_not_blank(dto.password, "sysuser.password.require", accept_language)
        self._require_not_blank(dto.captcha_id, "sysuser.uuid.require", accept_language)
        assert dto.phone is not None
        assert dto.code is not None
        assert dto.password is not None
        assert dto.captcha_id is not None
        if not PHONE_PATTERN.fullmatch(dto.phone):
            raise AppError(10074)
        user = await self.repository.get_user_by_username(dto.phone)
        if user is None:
            raise AppError(10071)
        if not await self.captcha.validate_sms_code(dto.phone, dto.code, delete=False):
            raise AppError(10075)
        password = await self._decrypt_and_validate_captcha(dto.password, dto.captcha_id)
        if not STRONG_PASSWORD.fullmatch(password):
            raise AppError(ErrorCode.PASSWORD_WEAK_ERROR)
        await self.repository.update_password(int(user["id"]), bcrypt_hash(password), shanghai_now_naive())
        await self.repository.session.commit()

    async def send_sms_verification(self, dto: SmsVerificationRequest) -> None:
        if not await self.captcha.validate(dto.captcha_id, dto.captcha, delete=False):
            raise AppError(10067)
        if not await self._mobile_registration_enabled():
            raise AppError(10068)
        phone_key = "null" if dto.phone is None else dto.phone
        last_send_key = f"sms:Validate:Code:{phone_key}:last_send_time"
        current_ms = int(time.time() * 1000)
        created = await cast(Any, self.redis.set)(last_send_key, str(current_ms), ex=60, nx=True)
        if not created:
            raw_last = await cast(Any, self.redis.get)(last_send_key)
            if raw_last is not None:
                last_ms = int(raw_last.decode() if isinstance(raw_last, bytes) else raw_last)
                difference = current_ms - last_ms
                if difference < 60_000:
                    raise AppError(10060, params=(str(max(0, (60_000 - difference) // 1000)),))

        today_key = f"sms:Validate:Code:{phone_key}:today_count"
        raw_count = await cast(Any, self.redis.get)(today_key)
        decoded_count = JavaRedisCodec.decode(raw_count)
        today_count = int(decoded_count or 0)
        raw_maximum = await self._get_param("server.sms_max_send_count", from_cache=True)
        maximum = int(raw_maximum) if raw_maximum is not None and raw_maximum != "" else 5
        if today_count >= maximum:
            raise AppError(10047)

        code = "".join(secrets.choice(string.digits) for _ in range(6))
        await self.captcha.set_sms_code(dto.phone, code)
        new_count = await cast(Any, self.redis.incr)(today_key)
        if int(new_count) == 1:
            await cast(Any, self.redis.expire)(today_key, 24 * 60 * 60)
        try:
            await self.sms_sender.send_verification_code(dto.phone, code)
        except AppError:
            # Java raises connection-construction failures before entering its refundable send attempt.
            raise
        except Exception as exc:
            logger.warning("Aliyun SMS request failed", exc_info=exc)
            await cast(Any, self.redis.delete)(today_key)
            raise AppError(10055) from exc

    async def public_config(self) -> dict[str, Any]:
        public_key = await self._get_param("server.public_key", from_cache=True)
        if public_key is None or not public_key.strip():
            raise AppError(10129)
        menu_config = await self._get_param("system-web.menu", from_cache=True)
        result: dict[str, Any] = {
            "enableMobileRegister": await self._mobile_registration_enabled(),
            "version": "0.9.5",
            "year": f"©{shanghai_now_naive().year}",
            "allowUserRegister": await self.allow_user_register(),
            "mobileAreaList": await self._dict_data_by_type("MOBILE_AREA"),
            "beianIcpNum": await self._get_param("server.beian_icp_num", from_cache=True),
            "beianGaNum": await self._get_param("server.beian_ga_num", from_cache=True),
            "name": await self._get_param("server.name", from_cache=True),
            "sm2PublicKey": public_key,
        }
        if menu_config is not None and menu_config.strip():
            result["systemWebMenu"] = json.loads(menu_config)
        return result

    async def allow_user_register(self) -> bool:
        value = await self._get_param("server.allow_user_register", from_cache=True)
        if value == "true":
            return True
        return await self.repository.count_users() == 0

    async def _create_token(self, user_id: int) -> str:
        now = shanghai_now_naive()
        expire_date = now + timedelta(seconds=TOKEN_EXPIRE_SECONDS)
        current = await self.repository.get_token_by_user_id(user_id, for_update=True)
        if current is None:
            token = generate_database_token()
            await self.repository.insert_token(
                token_id=snowflake.next_id(),
                user_id=user_id,
                token=token,
                now=now,
                expire_date=expire_date,
            )
            return token
        stored_expiry = self._datetime(current.get("expire_date"))
        token = str(current["token"])
        if stored_expiry is None or stored_expiry < now:
            token = generate_database_token()
        await self.repository.update_token(
            token_id=int(current["id"]),
            token=token,
            now=now,
            expire_date=expire_date,
        )
        return token

    async def _decrypt_and_validate_captcha(
        self,
        encrypted_password: str | None,
        captcha_id: str | None,
    ) -> str:
        private_key = await self._get_param("server.private_key", from_cache=True)
        if private_key is None or not private_key.strip():
            raise AppError(10129)
        try:
            if encrypted_password is None:
                raise ValueError("encrypted password is null")
            content = sm2_decrypt_c1c3c2(private_key, encrypted_password)
        except Exception as exc:
            raise AppError(10130) from exc
        if len(content) > CAPTCHA_LENGTH:
            embedded_captcha = content[:CAPTCHA_LENGTH]
            if not await self.captcha.validate(captcha_id, embedded_captcha, delete=True):
                raise AppError(10067)
            return content[CAPTCHA_LENGTH:]
        if content:
            raise AppError(10067)
        raise AppError(10130)

    async def _mobile_registration_enabled(self) -> bool:
        value = await self._get_param("server.enable_mobile_register", from_cache=True)
        if value is None or not value.strip():
            return False
        try:
            parsed = json.loads(value.lower())
        except json.JSONDecodeError as exc:
            raise AppError(ErrorCode.PARAMS_GET_ERROR) from exc
        return bool(parsed)

    async def _get_param(self, code: str, *, from_cache: bool) -> str | None:
        if from_cache:
            cached = JavaRedisCodec.decode(await cast(Any, self.redis.hget)("sys:params", code))
            if cached is not None:
                return str(cached)
        value = await self.repository.get_param_value(code)
        if from_cache and value is not None:
            await cast(Any, self.redis.hset)("sys:params", code, JavaRedisCodec.encode(value))
            await cast(Any, self.redis.expire)("sys:params", 24 * 60 * 60)
        return value

    async def _dict_data_by_type(self, dict_type: str) -> list[dict[str, Any]]:
        key = f"sys:dict:data:{dict_type}"
        cached = JavaRedisCodec.decode(await cast(Any, self.redis.get)(key))
        if isinstance(cached, list):
            return cast(list[dict[str, Any]], cached)
        values = await self.repository.get_mobile_area_items()
        await cast(Any, self.redis.set)(
            key,
            JavaRedisCodec.encode(
                values,
                item_java_type="xiaozhi.modules.sys.vo.SysDictDataItem",
            ),
            ex=24 * 60 * 60,
        )
        return values

    @staticmethod
    def _client_hash(request: Request) -> str:
        user_agent = request.headers.get("User-Agent", "").lower()
        forwarded_headers = (
            "x-forwarded-for",
            "Proxy-Client-IP",
            "WL-Proxy-Client-IP",
            "HTTP_CLIENT_IP",
            "HTTP_X_FORWARDED_FOR",
        )
        ip_address = next(
            (
                value
                for header in forwarded_headers
                if (value := request.headers.get(header)) and value.casefold() != "unknown"
            ),
            request.client.host if request.client else "",
        )
        date = shanghai_now_naive().strftime("%Y-%m-%d")
        return hashlib.md5(  # noqa: S324 - Java clientHash compatibility requires MD5
            f"{ip_address}{date}{user_agent}".encode(), usedforsecurity=False
        ).hexdigest()

    @staticmethod
    def _datetime(value: Any) -> datetime | None:
        if value is None or isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise TypeError(f"Unsupported database datetime value: {type(value).__name__}")

    @staticmethod
    def _require_not_blank(value: str | None, key: str, accept_language: str | None) -> None:
        if value is None or not value.strip():
            raise AppError(500, validation_message(key, accept_language))
