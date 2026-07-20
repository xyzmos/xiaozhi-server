from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import string
import time
import uuid
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

import httpx
from redis.asyncio import Redis
from websockets.asyncio.client import connect

from app.core.config import get_settings
from app.core.crypto import bcrypt_hash
from app.core.errors import AppError, ErrorCode
from app.core.ids import snowflake
from app.core.redis import JavaRedisCodec, get_redis
from app.core.security import AuthUser, shanghai_now_naive
from app.repositories.sys import SysRepository
from app.schemas.sys import DictDataPayload, DictTypePayload, EmitServerActionRequest, SysParamPayload
from app.services.java_validation import validation_message

logger = logging.getLogger(__name__)
WS_PATTERN = re.compile(r"^wss?://[\w.-]+(?:\.[\w.-]+)*(?::\d+)?(?:/[\w.-]*)*$")


class AdminService:
    def __init__(self, repository: SysRepository):
        self.repository = repository

    async def page_users(self, *, mobile: str | None, page: int, limit: int) -> dict[str, Any]:
        rows, total = await self.repository.page_users(
            mobile=mobile,
            page=max(1, page),
            limit=max(0, limit),
        )
        values = [
            {
                "deviceCount": str(row.get("device_count") or 0),
                "mobile": row.get("username"),
                "status": row.get("status"),
                "userid": str(row["id"]),
                "createDate": row.get("create_date"),
            }
            for row in rows
        ]
        return {"list": values, "total": total}

    async def reset_password(self, user_id: int, user: AuthUser) -> str:
        password = self._generate_password()
        await self.repository.reset_user_password(user_id, bcrypt_hash(password), user.id, shanghai_now_naive())
        await self.repository.session.commit()
        return password

    async def delete_user(self, user_id: int) -> None:
        try:
            await self.repository.delete_user_cascade(user_id)
            await self.repository.session.commit()
        except Exception:
            await self.repository.session.rollback()
            raise

    async def change_status(self, status: int, user_ids: list[str], user: AuthUser) -> None:
        # SysUserServiceImpl.changeStatus has an outer Spring transaction: a later
        # parse/update failure rolls back every earlier item in the same request.
        try:
            for value in user_ids:
                await self.repository.change_user_status(status, [int(value)], user.id, shanghai_now_naive())
            await self.repository.session.commit()
        except Exception:
            await self.repository.session.rollback()
            raise

    async def page_devices(self, *, keywords: str | None, page: int, limit: int) -> dict[str, Any]:
        rows, total = await self.repository.page_devices(
            keywords=keywords,
            page=max(1, page),
            limit=max(0, limit),
        )
        result = []
        for row in rows:
            result.append(
                {
                    "appVersion": row.get("app_version"),
                    "bindUserName": row.get("bind_user_name"),
                    "deviceType": row.get("board"),
                    "board": row.get("board"),
                    "id": row.get("id"),
                    "macAddress": row.get("mac_address"),
                    "alias": row.get("alias"),
                    "otaUpgrade": None,
                    "recentChatTime": self._short_time(cast(datetime | str | None, row.get("update_date"))),
                    "lastConnectedAtTimestamp": self._timestamp_ms(
                        cast(datetime | str | None, row.get("last_connected_at"))
                    ),
                    "createDateTimestamp": self._timestamp_ms(
                        cast(datetime | str | None, row.get("create_date"))
                    ),
                    "createDate": self._utc_datetime_string(
                        cast(datetime | str | None, row.get("create_date"))
                    ),
                }
            )
        return {"list": result, "total": total}

    @staticmethod
    def _generate_password() -> str:
        characters = string.ascii_letters + string.digits + "!@#$%^&*()"
        values = [
            secrets.choice(string.digits),
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.ascii_uppercase),
            secrets.choice("!@#$%^&*()"),
        ]
        values.extend(secrets.choice(characters) for _ in range(8))
        secrets.SystemRandom().shuffle(values)
        return "".join(values)

    @staticmethod
    def _timestamp_ms(value: datetime | str | None) -> int | None:
        value = AdminService._database_datetime(value)
        if value is None:
            return None
        timezone = ZoneInfo(get_settings().timezone)
        localized = value if value.tzinfo else value.replace(tzinfo=timezone)
        return int(localized.timestamp() * 1000)

    @staticmethod
    def _short_time(value: datetime | str | None) -> str | None:
        value = AdminService._database_datetime(value)
        if value is None:
            return None
        now = shanghai_now_naive()
        if value.tzinfo:
            value = value.astimezone(ZoneInfo(get_settings().timezone)).replace(tzinfo=None)
        seconds = int((now - value).total_seconds())
        if seconds <= 10:
            return "刚刚"
        if seconds < 60:
            return f"{seconds}秒前"
        if seconds < 3600:
            return f"{seconds // 60}分钟前"
        if seconds < 86400:
            return f"{seconds // 3600}小时前"
        if seconds < 604800:
            return f"{seconds // 86400}天前"
        return value.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _utc_datetime_string(value: datetime | str | None) -> str | None:
        value = AdminService._database_datetime(value)
        if value is None:
            return None
        timezone = ZoneInfo(get_settings().timezone)
        localized = value if value.tzinfo else value.replace(tzinfo=timezone)
        return localized.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _database_datetime(value: datetime | str | None) -> datetime | None:
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        return value


class ParamExternalValidator:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client

    async def validate(self, code: str, value: str) -> None:
        if code == "server.websocket":
            await self._websockets(value)
        elif code == "server.ota":
            await self._http_endpoint(value, kind="ota")
        elif code == "server.mcp_endpoint":
            await self._http_endpoint(value, kind="mcp")
        elif code == "server.voice_print":
            await self._http_endpoint(value, kind="voiceprint")
        elif code == "server.mqtt_signature_key":
            self._mqtt_secret(value)

    async def _websockets(self, value: str) -> None:
        urls = value.split(";")
        while urls and urls[-1] == "":
            urls.pop()
        if not urls:
            raise AppError(10098)
        for raw_url in urls:
            if not raw_url.strip():
                continue
            if "localhost" in raw_url or "127.0.0.1" in raw_url:
                raise AppError(10099)
            if not WS_PATTERN.fullmatch(raw_url.strip()):
                raise AppError(10100)
            try:
                async with connect(raw_url, open_timeout=5):
                    pass
            except Exception as exc:
                raise AppError(10101) from exc

    async def _http_endpoint(self, value: str, *, kind: str) -> None:
        if not value.strip() or value == "null":
            return
        if "localhost" in value or "127.0.0.1" in value:
            raise AppError({"ota": 10103, "mcp": 10110, "voiceprint": 10116}[kind])
        if kind == "ota":
            if not value.lower().startswith("http"):
                raise AppError(10104)
            if not value.endswith("/ota/"):
                raise AppError(10105)
        elif kind == "mcp":
            if "key" not in value.lower():
                raise AppError(10111)
        else:
            if "key" not in value.lower():
                raise AppError(10117)
            if not value.lower().startswith("http"):
                raise AppError(10118)

        final_code = {"ota": 10108, "mcp": 10114, "voiceprint": 10121}[kind]
        marker = {"ota": "OTA", "mcp": "success", "voiceprint": "healthy"}[kind]
        try:
            if self.client is not None:
                response = await self.client.get(value)
            else:
                async with httpx.AsyncClient(timeout=get_settings().external_request_timeout_seconds) as client:
                    response = await client.get(value)
            if response.status_code != 200 or marker not in response.text:
                raise ValueError("external endpoint response did not match Java validation")
        except Exception as exc:
            raise AppError(final_code) from exc

    @staticmethod
    def _mqtt_secret(secret: str) -> None:
        if not secret.strip() or secret == "null":  # noqa: S105 - sentinel value from the Java parameter table
            raise AppError(10122)
        if len(secret) < 8:
            raise AppError(10123)
        if not re.search(r"[a-z]", secret) or not re.search(r"[A-Z]", secret):
            raise AppError(10124)
        lowered = secret.lower()
        if any(weak in lowered for weak in ("test", "1234", "admin", "password", "qwerty", "xiaozhi")):
            raise AppError(10125)


class SysParamService:
    def __init__(
        self,
        repository: SysRepository,
        *,
        redis: Redis | None = None,
        validator: ParamExternalValidator | None = None,
    ):
        self.repository = repository
        self.redis = redis or get_redis()
        self.validator = validator or ParamExternalValidator()

    async def page(
        self,
        *,
        param_code: str | None,
        page: int,
        limit: int,
        order_field: str | None,
        order: str | None,
    ) -> dict[str, Any]:
        rows, total = await self.repository.page_params(
            param_code=param_code,
            page=max(1, page),
            limit=max(0, limit),
            order_field=order_field,
            order=order,
        )
        return {"list": [self._param_dto(row) for row in rows], "total": total}

    async def get(self, param_id: int) -> dict[str, Any] | None:
        row = await self.repository.get_param(param_id)
        return None if row is None else self._param_dto(row)

    async def save(
        self,
        dto: SysParamPayload,
        user: AuthUser,
        accept_language: str | None = None,
    ) -> None:
        self._validate_group(dto, update=False, accept_language=accept_language)
        self._validate_value(dto)
        assert dto.param_code is not None
        assert dto.param_value is not None
        assert dto.value_type is not None
        await self.repository.insert_param(
            param_id=snowflake.next_id(),
            param_code=dto.param_code,
            param_value=dto.param_value,
            value_type=dto.value_type,
            remark=dto.remark,
            user_id=user.id,
            now=shanghai_now_naive(),
        )
        await self._cache_set(dto.param_code, dto.param_value)
        await self.repository.session.commit()

    async def update(
        self,
        dto: SysParamPayload,
        user: AuthUser,
        accept_language: str | None = None,
    ) -> None:
        self._validate_group(dto, update=True, accept_language=accept_language)
        assert dto.id is not None
        assert dto.param_code is not None
        assert dto.param_value is not None
        assert dto.value_type is not None
        # These checks live in the Java controller and therefore run before
        # SysParamsService.update validates the declared value type.
        await self.validator.validate(dto.param_code, dto.param_value)
        if dto.param_code == "system-web.menu":
            await self._update_system_web_menu(dto.param_value, user)
        else:
            self._validate_value(dto)
            await self.repository.update_param(
                param_id=dto.id,
                param_code=dto.param_code,
                param_value=dto.param_value,
                value_type=dto.value_type,
                remark=dto.remark,
                user_id=user.id,
                now=shanghai_now_naive(),
            )
            await self._cache_set(dto.param_code, dto.param_value)
        await self.repository.session.commit()

    async def delete(self, ids: list[str]) -> None:
        if not ids:
            raise AppError(10001, "id")
        parsed_ids = [int(value) for value in ids]
        codes = await self.repository.param_codes_for_ids(parsed_ids)
        if codes:
            await cast(Any, self.redis.hdel)("sys:params", *codes)
        await self.repository.delete_params(parsed_ids)
        await self.repository.session.commit()

    async def get_value(self, code: str, *, from_cache: bool = True) -> str | None:
        if from_cache:
            cached = JavaRedisCodec.decode(await cast(Any, self.redis.hget)("sys:params", code))
            if cached is not None:
                return str(cached)
        value = await self.repository.get_param_value(code)
        if value is not None and from_cache:
            await self._cache_set(code, value)
        return value

    async def config_rows(self) -> list[dict[str, Any]]:
        return await self.repository.list_config_params()

    async def _update_system_web_menu(self, config_json: str, user: AuthUser) -> None:
        current_config = await self.repository.get_param_value("system-web.menu")
        try:
            current = json.loads(current_config) if current_config and current_config.strip() else None
            updated = json.loads(config_json) if config_json.strip() else None
        except json.JSONDecodeError as exc:
            raise AppError(ErrorCode.PARAM_JSON_INVALID) from exc
        if isinstance(current, dict) and isinstance(updated, dict):
            current_features = current.get("features")
            updated_features = updated.get("features")
            # Java only evaluates addressBook when both feature maps are present.
            if isinstance(current_features, dict) and isinstance(updated_features, dict):
                current_address = current_features.get("addressBook")
                updated_address = updated_features.get("addressBook")
                current_enabled = self._java_enabled(current_address)
                updated_enabled = self._java_enabled(updated_address)
                if current_enabled and not updated_enabled:
                    await self.repository.delete_plugin_mapping_by_plugin_id("SYSTEM_PLUGIN_CALL_DEVICE")
        await self.repository.update_param_value_by_code(
            "system-web.menu", config_json, user.id, shanghai_now_naive()
        )
        await self._cache_set("system-web.menu", config_json)

    async def _cache_set(self, code: str, value: str) -> None:
        await cast(Any, self.redis.hset)("sys:params", code, JavaRedisCodec.encode(value))
        await cast(Any, self.redis.expire)("sys:params", 24 * 60 * 60)

    @staticmethod
    def _java_enabled(address_book: Any) -> bool:
        if not isinstance(address_book, dict):
            return False
        value = address_book.get("enabled")
        if value is None:
            return False
        if not isinstance(value, bool):
            # The Java implementation casts the JSON value to Boolean.
            raise TypeError("addressBook.enabled must be a boolean")
        return value

    @staticmethod
    def _validate_value(dto: SysParamPayload) -> None:
        assert dto.param_value is not None
        assert dto.value_type is not None
        if not dto.param_value.strip():
            raise AppError(ErrorCode.PARAM_VALUE_NULL)
        if not dto.value_type.strip():
            raise AppError(ErrorCode.PARAM_TYPE_NULL)
        value_type = dto.value_type.lower()
        if value_type in {"string", "array"}:
            return
        if value_type == "number":
            try:
                float(dto.param_value)
            except ValueError as exc:
                raise AppError(ErrorCode.PARAM_NUMBER_INVALID) from exc
            return
        if value_type == "boolean":
            if dto.param_value.lower() not in {"true", "false"}:
                raise AppError(ErrorCode.PARAM_BOOLEAN_INVALID)
            return
        if value_type == "json":
            stripped = dto.param_value.strip()
            if not stripped.startswith("{") or not stripped.endswith("}"):
                raise AppError(ErrorCode.PARAM_JSON_INVALID)
            try:
                json.loads(dto.param_value)
            except json.JSONDecodeError as exc:
                raise AppError(ErrorCode.PARAM_JSON_INVALID) from exc
            return
        raise AppError(ErrorCode.PARAM_TYPE_INVALID)

    @staticmethod
    def _validate_group(
        dto: SysParamPayload,
        *,
        update: bool,
        accept_language: str | None,
    ) -> None:
        def fail(key: str) -> None:
            raise AppError(500, validation_message(key, accept_language))

        if update and dto.id is None:
            fail("id.require")
        if not update and dto.id is not None:
            fail("id.null")
        if dto.param_code is None or not dto.param_code.strip():
            fail("sysparams.paramcode.require")
        if dto.param_value is None or not dto.param_value.strip():
            fail("sysparams.paramvalue.require")
        if dto.value_type is None or not dto.value_type.strip():
            fail("sysparams.valuetype.require")
        if dto.value_type not in {"string", "number", "boolean", "array", "json"}:
            fail("sysparams.valuetype.pattern")

    @staticmethod
    def _param_dto(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "paramCode": row.get("param_code"),
            "paramValue": row.get("param_value"),
            "valueType": row.get("value_type"),
            "remark": row.get("remark"),
            "createDate": row.get("create_date"),
            "updateDate": row.get("update_date"),
        }


class DictService:
    def __init__(self, repository: SysRepository, *, redis: Redis | None = None):
        self.repository = repository
        self.redis = redis or get_redis()

    async def page_types(
        self,
        *,
        dict_type: str | None,
        dict_name: str | None,
        page: int,
        limit: int,
    ) -> dict[str, Any]:
        rows, total = await self.repository.page_dict_types(
            dict_type=dict_type,
            dict_name=dict_name,
            page=max(1, page),
            limit=max(0, limit),
        )
        return {"list": [self._type_vo(row, include_names=True) for row in rows], "total": total}

    async def get_type(self, type_id: int) -> dict[str, Any]:
        row = await self.repository.get_dict_type(type_id)
        if row is None:
            raise AppError(10076)
        return self._type_vo(row, include_names=False)

    async def save_type(self, dto: DictTypePayload, user: AuthUser) -> None:
        if await self.repository.dict_type_exists(dto.dict_type):
            raise AppError(10077)
        await self.repository.insert_dict_type(
            type_id=dto.id if dto.id is not None else snowflake.next_id(),
            dict_type=dto.dict_type,
            dict_name=dto.dict_name,
            remark=dto.remark,
            sort=dto.sort,
            user_id=user.id,
            now=shanghai_now_naive(),
        )
        await self.repository.session.commit()

    async def update_type(self, dto: DictTypePayload, user: AuthUser) -> None:
        if await self.repository.dict_type_exists(dto.dict_type, exclude_id=dto.id):
            raise AppError(10077)
        await self.repository.update_dict_type(
            type_id=dto.id,
            dict_type=dto.dict_type,
            dict_name=dto.dict_name,
            remark=dto.remark,
            sort=dto.sort,
            user_id=user.id,
            now=shanghai_now_naive(),
        )
        await self.repository.session.commit()

    async def delete_types(self, ids: list[int]) -> None:
        await self.repository.delete_dict_types(ids)
        await self.repository.session.commit()

    async def page_data(
        self,
        *,
        dict_type_id: int,
        dict_label: str | None,
        dict_value: str | None,
        page: int,
        limit: int,
    ) -> dict[str, Any]:
        rows, total = await self.repository.page_dict_data(
            dict_type_id=dict_type_id,
            dict_label=dict_label,
            dict_value=dict_value,
            page=max(1, page),
            limit=max(0, limit),
        )
        return {"list": [self._data_vo(row, include_names=True) for row in rows], "total": total}

    async def get_data(self, data_id: int) -> dict[str, Any] | None:
        row = await self.repository.get_dict_data(data_id)
        return None if row is None else self._data_vo(row, include_names=False)

    async def save_data(self, dto: DictDataPayload, user: AuthUser) -> None:
        # Java compares dict_label against dictValue here; retain that behavior for compatibility.
        if await self.repository.dict_data_label_exists(dto.dict_type_id, dto.dict_value):
            raise AppError(10128)
        await self.repository.insert_dict_data(
            data_id=dto.id if dto.id is not None else snowflake.next_id(),
            dict_type_id=dto.dict_type_id,
            dict_label=dto.dict_label,
            dict_value=dto.dict_value,
            remark=dto.remark,
            sort=dto.sort,
            user_id=user.id,
            now=shanghai_now_naive(),
        )
        await self._clear_dict_cache(dto.dict_type_id)
        await self.repository.session.commit()

    async def update_data(self, dto: DictDataPayload, user: AuthUser) -> None:
        if await self.repository.dict_data_label_exists(dto.dict_type_id, dto.dict_value, exclude_id=dto.id):
            raise AppError(10128)
        await self.repository.update_dict_data(
            data_id=dto.id,
            dict_type_id=dto.dict_type_id,
            dict_label=dto.dict_label,
            dict_value=dto.dict_value,
            remark=dto.remark,
            sort=dto.sort,
            user_id=user.id,
            now=shanghai_now_naive(),
        )
        await self._clear_dict_cache(dto.dict_type_id)
        await self.repository.session.commit()

    async def delete_data(self, ids: list[int]) -> None:
        if ids:
            codes = await self.repository.dict_type_codes_for_data_ids(ids)
            if codes:
                await cast(Any, self.redis.delete)(*[f"sys:dict:data:{code}" for code in codes])
            await self.repository.delete_dict_data(ids)
        await self.repository.session.commit()

    async def items(self, dict_type: str) -> list[dict[str, Any]] | None:
        if not dict_type.strip():
            return None
        key = f"sys:dict:data:{dict_type}"
        cached = JavaRedisCodec.decode(await cast(Any, self.redis.get)(key))
        if isinstance(cached, list):
            return cast(list[dict[str, Any]], cached)
        rows = await self.repository.dict_items(dict_type)
        await cast(Any, self.redis.set)(
            key,
            JavaRedisCodec.encode(
                rows,
                item_java_type="xiaozhi.modules.sys.vo.SysDictDataItem",
            ),
            ex=24 * 60 * 60,
        )
        return rows

    async def _clear_dict_cache(self, type_id: int | None) -> None:
        dict_type = await self.repository.dict_type_code(type_id)
        if dict_type is not None:
            await cast(Any, self.redis.delete)(f"sys:dict:data:{dict_type}")

    @staticmethod
    def _type_vo(row: dict[str, Any], *, include_names: bool) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "dictType": row.get("dict_type"),
            "dictName": row.get("dict_name"),
            "remark": row.get("remark"),
            "sort": row.get("sort"),
            "creator": row.get("creator"),
            "creatorName": row.get("creator_name") if include_names else None,
            "createDate": row.get("create_date"),
            "updater": row.get("updater"),
            "updaterName": row.get("updater_name") if include_names else None,
            "updateDate": row.get("update_date"),
        }

    @staticmethod
    def _data_vo(row: dict[str, Any], *, include_names: bool) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "dictTypeId": row.get("dict_type_id"),
            "dictLabel": row.get("dict_label"),
            "dictValue": row.get("dict_value"),
            "remark": row.get("remark"),
            "sort": row.get("sort"),
            "creator": row.get("creator"),
            "creatorName": row.get("creator_name") if include_names else None,
            "createDate": row.get("create_date"),
            "updater": row.get("updater"),
            "updaterName": row.get("updater_name") if include_names else None,
            "updateDate": row.get("update_date"),
        }


class ServerActionService:
    def __init__(self, param_service: SysParamService, *, redis: Redis | None = None):
        self.param_service = param_service
        self.redis = redis or get_redis()

    async def server_list(self) -> list[str]:
        value = await self.param_service.get_value("server.websocket", from_cache=True)
        if value is None or not value.strip():
            return []
        values = value.split(";")
        while values and values[-1] == "":
            values.pop()
        return values

    async def emit(self, dto: EmitServerActionRequest) -> bool:
        action = dto.action.lower() if dto.action is not None else None
        if action not in {"restart", "update_config"}:
            raise AppError(10095)
        websocket_text = await self.param_service.get_value("server.websocket", from_cache=True)
        if websocket_text is None or not websocket_text.strip():
            raise AppError(10096)
        if dto.target_ws not in websocket_text.split(";"):
            raise AppError(10097)
        payload_secret = await self.param_service.get_value("server.secret", from_cache=True)
        device_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())
        await cast(Any, self.redis.set)(
            f"tmp_register_mac:{device_id}",
            JavaRedisCodec.encode("true"),
            ex=300,
        )
        authentication_secret = await self.param_service.get_value("server.secret", from_cache=False)
        if authentication_secret is None or not authentication_secret.strip():
            raise AppError(10045)
        timestamp = int(time.time())
        content = f"{client_id}|{device_id}|{timestamp}"
        signature = hmac.new(authentication_secret.encode(), content.encode(), digestmod=hashlib.sha256).digest()
        token = base64.urlsafe_b64encode(signature).rstrip(b"=").decode() + f".{timestamp}"
        headers = {
            "device-id": device_id,
            "client-id": client_id,
            "authorization": f"Bearer {token}",
        }
        if payload_secret is None:
            raise AppError(10045)
        payload = {"type": "server", "action": action, "content": {"secret": payload_secret}}
        try:
            async with connect(dto.target_ws, additional_headers=headers, open_timeout=3) as websocket:
                await websocket.send(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                deadline = time.monotonic() + 120
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
                    response = json.loads(raw)
                    if (
                        isinstance(response, dict)
                        and response.get("status") == "success"
                        and response.get("type") == "server"
                        and isinstance(response.get("content"), dict)
                        and response["content"].get("action") is not None
                    ):
                        return True
        except Exception as exc:
            raise AppError(10045) from exc
