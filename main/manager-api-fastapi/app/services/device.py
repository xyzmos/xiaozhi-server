from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import random
import re
import secrets
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.errors import AppError
from app.core.redis import JavaRedisCodec, get_redis
from app.core.security import AuthUser, shanghai_now_naive
from app.integrations.mqtt_gateway import post_json
from app.repositories.device import DeviceRepository
from app.schemas.device import DeviceManualAddRequest, DeviceReportRequest, DeviceUpdateRequest, OtaRecord
from app.services.system_params import SystemParamService

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 24 * 60 * 60
INVALID_FIRMWARE_URL = (
    "http://xiaozhi.server.com:8002/xiaozhi/otaMag/download/NOT_ACTIVATED_FIRMWARE_THIS_IS_A_INVALID_URL"
)
MAC_PATTERN = re.compile(r"^([0-9A-Za-z]{2}[:-]){5}([0-9A-Za-z]{2})$")
OTA_ORDER_COLUMNS = {
    "id": "id",
    "firmwareName": "firmware_name",
    "firmware_name": "firmware_name",
    "type": "type",
    "version": "version",
    "size": "size",
    "sort": "sort",
    "updateDate": "update_date",
    "update_date": "update_date",
    "createDate": "create_date",
    "create_date": "create_date",
}


def is_blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _java_semicolon_split(value: str) -> list[str]:
    parts = value.split(";")
    while parts and parts[-1] == "":
        parts.pop()
    return parts


def _mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if "@class" in value:
            return {str(key): item for key, item in value.items() if key != "@class"}
        return {str(key): item for key, item in value.items()}
    if isinstance(value, list) and len(value) == 2 and isinstance(value[1], dict):
        return {str(key): item for key, item in value[1].items()}
    return None


async def redis_get(key: str, client: Redis | None = None) -> Any:
    selected = client or get_redis()
    raw = await cast(Any, selected.get(key))
    return JavaRedisCodec.decode(raw)


async def redis_set(key: str, value: Any, *, ttl: int = DEFAULT_TTL_SECONDS, client: Redis | None = None) -> None:
    selected = client or get_redis()
    await cast(Any, selected.set(key, JavaRedisCodec.encode(value), ex=ttl))


async def redis_delete(*keys: str, client: Redis | None = None) -> None:
    if not keys:
        return
    selected = client or get_redis()
    await cast(Any, selected.delete(*keys))


async def redis_increment(key: str, *, ttl: int = DEFAULT_TTL_SECONDS, client: Redis | None = None) -> int:
    selected = client or get_redis()
    value = int(await cast(Any, selected.incr(key)))
    await cast(Any, selected.expire(key, ttl))
    return value


class DeviceService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        redis_client: Redis | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.session = session
        self.repository = DeviceRepository(session)
        self.params = SystemParamService(session)
        self.redis = redis_client
        self.http_client = http_client

    async def register_device(self, mac_address: str) -> str:
        while True:
            code = f"{secrets.randbelow(1_000_000):06d}"
            key = f"sys:device:captcha:{code}"
            if is_blank(cast(str | None, await redis_get(key, self.redis))):
                await redis_set(key, mac_address, client=self.redis)
                return code

    async def activate_bound_device(self, *, agent_id: str, activation_code: str, user: AuthUser) -> None:
        if is_blank(activation_code):
            raise AppError(10061)
        code_key = f"ota:activation:code:{activation_code}"
        device_id_value = await redis_get(code_key, self.redis)
        if device_id_value in (None, ""):
            raise AppError(10062)
        device_id = str(device_id_value)
        safe_device_id = device_id.replace(":", "_").lower()
        data_key = f"ota:activation:data:{safe_device_id}"
        cached = _mapping(await redis_get(data_key, self.redis))
        if cached is None or str(cached.get("activation_code") or "") != activation_code:
            raise AppError(10062)
        if await self.repository.get_device(device_id) is not None:
            raise AppError(10063)

        now = shanghai_now_naive()
        values = {
            "id": device_id,
            "user_id": user.id,
            "mac_address": cached.get("mac_address"),
            "last_connected_at": now,
            "auto_update": 1,
            "board": cached.get("board"),
            "alias": None,
            "agent_id": agent_id,
            "app_version": cached.get("app_version"),
            "sort": None,
            "updater": user.id,
            "update_date": now,
            "creator": user.id,
            "create_date": now,
        }
        try:
            await self.repository.insert_device(values)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        await redis_delete(data_key, code_key, f"agent:device:count:{agent_id}", client=self.redis)

    async def list_user_devices(self, user_id: int, agent_id: str) -> list[dict[str, Any]]:
        devices = await self.repository.get_user_devices(user_id, agent_id)
        return [self._user_device_view(row) for row in devices]

    async def get_online_data(self, agent_id: str, user: AuthUser) -> str:
        gateway = await self.params.get_value("server.mqtt_manager_api", from_cache=True)
        if is_blank(gateway) or gateway == "null":
            return ""
        devices = await self.repository.get_user_devices(user.id, agent_id)
        client_ids = {
            self._mqtt_client_id(
                str(device.get("board") or "GID_default"),
                str(device.get("mac_address") or "unknown"),
            )
            for device in devices
        }
        if not client_ids:
            return ""
        signature_key = await self.params.get_value("server.mqtt_signature_key", from_cache=False)
        return await post_json(
            f"http://{gateway}/api/devices/status",
            {"clientIds": sorted(client_ids)},
            signature_key or "",
            timeout_seconds=get_settings().external_request_timeout_seconds,
            client=self.http_client,
        )

    async def unbind(self, *, user_id: int, device_id: str) -> None:
        device = await self.repository.get_device(device_id)
        if device is None:
            return
        mac_address = device.get("mac_address")
        agent_id = device.get("agent_id")
        if not is_blank(None if agent_id is None else str(agent_id)):
            await redis_delete(f"agent:device:count:{agent_id}", client=self.redis)
        try:
            await self.repository.delete_device_for_user(device_id, user_id)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        try:
            if mac_address is not None:
                await self.repository.delete_address_books_for_macs([str(mac_address)])
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        await self.refresh_address_book_cache()

    async def update_device(
        self,
        *,
        device_id: str,
        request: DeviceUpdateRequest,
        user: AuthUser,
    ) -> bool:
        device = await self.repository.get_device(device_id)
        if device is None or int(device.get("user_id") or -1) != user.id:
            return False
        await self.repository.update_device_info(
            device_id,
            auto_update=request.auto_update,
            alias=request.alias,
            updater=user.id,
            now=shanghai_now_naive(),
        )
        await self.session.commit()
        return True

    async def manual_add(self, *, request: DeviceManualAddRequest, user: AuthUser) -> None:
        mac_address = request.mac_address
        if mac_address is not None and await self.repository.get_device_by_mac(mac_address) is not None:
            raise AppError(10161)
        now = shanghai_now_naive()
        values = {
            "id": uuid.uuid4().hex if mac_address in (None, "") else mac_address,
            "user_id": user.id,
            "mac_address": mac_address,
            "last_connected_at": now,
            "auto_update": 1,
            "board": request.board,
            "alias": None,
            "agent_id": request.agent_id,
            "app_version": request.app_version,
            "sort": None,
            "updater": user.id,
            "update_date": now,
            "creator": user.id,
            "create_date": now,
        }
        try:
            await self.repository.insert_device(values)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        agent_cache_id = "null" if request.agent_id is None else request.agent_id
        await redis_delete(f"agent:device:count:{agent_cache_id}", client=self.redis)

    async def get_tools(self, *, device_id: str, user: AuthUser) -> dict[str, Any] | None:
        gateway_and_device = await self._gateway_device(device_id, user)
        if gateway_and_device is None:
            return None
        gateway, device = gateway_and_device
        client_id = self._mqtt_client_id(
            str(device.get("board") or "GID_default"),
            str(device.get("mac_address") or "unknown"),
        )
        url = f"http://{gateway}/api/commands/{client_id}"
        all_tools: list[Any] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"withUserTools": True}
            if cursor is not None and cursor.strip():
                params["cursor"] = cursor
            body = {
                "type": "mcp",
                "payload": {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": params},
            }
            response_body = await self._post_gateway(url, body)
            if is_blank(response_body):
                break
            payload = json.loads(response_body)
            if not isinstance(payload, dict) or not bool(payload.get("success", False)):
                break
            data = payload.get("data")
            if not isinstance(data, dict):
                break
            tools = data.get("tools")
            if isinstance(tools, list):
                all_tools.extend(tools)
            next_cursor = data.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor.strip():
                break
            cursor = next_cursor
        return None if not all_tools else {"tools": all_tools}

    async def call_tool(
        self,
        *,
        device_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None,
        user: AuthUser,
    ) -> Any:
        gateway_and_device = await self._gateway_device(device_id, user)
        if gateway_and_device is None:
            return None
        gateway, device = gateway_and_device
        client_id = self._mqtt_client_id(
            str(device.get("board") or "GID_default"),
            str(device.get("mac_address") or "unknown"),
        )
        response_body = await self._post_gateway(
            f"http://{gateway}/api/commands/{client_id}",
            {
                "type": "mcp",
                "payload": {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
            },
        )
        if is_blank(response_body):
            return None
        payload = json.loads(response_body)
        if not isinstance(payload, dict) or not bool(payload.get("success", False)):
            return None
        data = payload.get("data")
        content = data.get("content") if isinstance(data, dict) else None
        if not isinstance(content, list) or not content or not isinstance(content[0], dict):
            return None
        first = content[0]
        if first.get("type") != "text" or not isinstance(first.get("text"), str):
            return None
        text = str(first["text"])
        if not text.strip():
            return None
        trimmed = text.strip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            try:
                parsed = json.loads(trimmed)
                return parsed if isinstance(parsed, dict) else trimmed
            except json.JSONDecodeError:
                return trimmed
        if trimmed == "true":
            return True
        if trimmed == "false":
            return False
        return trimmed

    async def address_book(self, mac_address: str) -> list[dict[str, Any]]:
        rows = await self.repository.get_address_book(mac_address)
        for row in rows:
            if row.get("has_permission") is not None:
                row["has_permission"] = bool(row["has_permission"])
        return rows

    async def lookup_address_book(self, *, caller_mac: str, nickname: str) -> dict[str, str | None] | None:
        books = await self.all_address_books()
        caller_book = books.get(caller_mac.lower())
        if caller_book is None:
            return None
        target_with_permission = caller_book.get(nickname)
        if target_with_permission is None:
            return None
        parts = target_with_permission.split("|")
        target_mac = parts[0]
        has_permission = len(parts) > 1 and parts[1] == "1"
        target_book = books.get(target_mac.lower())
        if target_book is None:
            return None
        caller_nickname = target_book.get(caller_mac.lower())
        return {
            "targetMac": target_mac,
            "callerNickname": caller_nickname,
            "hasPermission": "true" if has_permission else "false",
        }

    async def call_by_nickname(self, *, caller_mac: str, nickname: str, answer: bool) -> dict[str, Any]:
        books = await self.all_address_books()
        if answer:
            return await self._post_call("/api/call/accept", {"mac": caller_mac}, "接听")
        caller_book = books.get(caller_mac.lower())
        if caller_book is None or nickname not in caller_book:
            return {"status": "error", "message": f"未找到备注为'{nickname}'的设备"}
        parts = caller_book[nickname].split("|")
        target_mac = parts[0]
        allowed = len(parts) > 1 and parts[1] == "1"
        if not allowed:
            return {"status": "error", "message": "呼叫失败，您没有权限呼叫该设备"}
        target_book = books.get(target_mac.lower())
        caller_nickname = target_book.get(caller_mac.lower()) if target_book is not None else None
        if is_blank(caller_nickname):
            caller = await self.repository.get_device_by_mac(caller_mac)
            if caller is None:
                raise RuntimeError("caller device does not exist")
            caller_nickname = None if caller.get("alias") is None else str(caller["alias"])
            if is_blank(caller_nickname):
                caller_nickname = self._mac_device_name(caller_mac)
        return await self._post_call(
            "/api/call/request",
            {"caller_mac": caller_mac, "target_mac": target_mac, "caller_nickname": caller_nickname},
            "呼叫",
        )

    async def save_address_book(
        self,
        *,
        mac_address: str,
        target_mac: str,
        alias: str | None,
        has_permission: bool | None,
        actor: int,
    ) -> None:
        record = await self.repository.get_address_book_record(mac_address, target_mac)
        now = shanghai_now_naive()
        if record is None:
            final_alias = alias
            if is_blank(final_alias):
                target = await self.repository.get_device_by_mac(target_mac)
                if target is None:
                    raise RuntimeError("target device does not exist")
                final_alias = None if target.get("alias") is None else str(target["alias"])
            final_alias = await self._unique_alias(mac_address, final_alias)
            await self.repository.insert_address_book(
                mac_address=mac_address,
                target_mac=target_mac,
                alias=final_alias,
                has_permission=has_permission,
                actor=actor,
                now=now,
            )
            await self.session.commit()
        else:
            if alias is not None:
                await self.repository.update_address_alias(
                    mac_address,
                    target_mac,
                    await self._unique_alias(mac_address, alias),
                    now=now,
                )
                await self.session.commit()
                await self.refresh_address_book_cache()
            if has_permission is not None:
                await self.repository.update_address_permission(
                    mac_address,
                    target_mac,
                    has_permission,
                    now=now,
                )
                await self.session.commit()
        await self.refresh_address_book_cache()

    async def all_address_books(self) -> dict[str, dict[str, str]]:
        cached = _mapping(await redis_get("device:address_book:all", self.redis))
        if cached is not None:
            result: dict[str, dict[str, str]] = {}
            for key, value in cached.items():
                nested = _mapping(value)
                if nested is not None:
                    result[key] = {str(field): str(item) for field, item in nested.items()}
            return result
        return await self.refresh_address_book_cache()

    async def refresh_address_book_cache(self) -> dict[str, dict[str, str]]:
        records = await self.repository.get_all_address_book()
        result: dict[str, dict[str, str]] = {}
        reverse: dict[str, str] = {}
        for record in records:
            mac_a = str(record["mac_address"]).lower()
            mac_b = str(record["target_mac"]).lower()
            alias = record.get("alias")
            if alias not in (None, ""):
                alias_string = str(alias)
                result.setdefault(mac_a, {})[alias_string] = (
                    f"{mac_b}|{'1' if bool(record.get('has_permission')) else '0'}"
                )
                reverse[f"{mac_b}:{mac_a}"] = alias_string
        for record in records:
            mac_a = str(record["mac_address"]).lower()
            mac_b = str(record["target_mac"]).lower()
            reverse_alias = reverse.get(f"{mac_a}:{mac_b}")
            if isinstance(reverse_alias, str) and reverse_alias:
                result.setdefault(mac_b, {})[mac_a] = reverse_alias
        await redis_set("device:address_book:all", result, client=self.redis)
        return result

    async def check_ota(
        self,
        *,
        device_id: str,
        client_id: str,
        report: DeviceReportRequest,
        request_url: str,
        client_ip: str,
        defer_connection_update: Callable[[str, str | None, str | None], None] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(tz=ZoneInfo(get_settings().timezone))
        utc_offset = now.utcoffset()
        response: dict[str, Any] = {
            "server_time": {
                "timestamp": int(now.timestamp() * 1000),
                "timeZone": get_settings().timezone,
                "timezone_offset": int((utc_offset.total_seconds() if utc_offset is not None else 0) / 60),
            },
            "activation": None,
            "error": None,
            "firmware": None,
            "websocket": None,
            "mqtt": None,
        }
        device = await self.repository.get_device_by_mac(device_id)
        if device is None:
            if report.application is None:
                raise RuntimeError("application is required")
            response["firmware"] = {
                "version": report.application.version,
                "url": INVALID_FIRMWARE_URL,
            }
        elif device.get("auto_update") is None:
            raise RuntimeError("auto_update is null")
        elif int(device["auto_update"]) != 0:
            ota_type = report.board.type if report.board is not None else None
            current_version = report.application.version if report.application is not None else None
            response["firmware"] = await self._firmware_info(ota_type, current_version, request_url)

        websocket_url = await self.params.get_value("server.websocket", from_cache=True)
        auth_enabled = await self.params.get_value("server.auth.enabled", from_cache=True)
        websocket_token = ""
        if (auth_enabled or "").lower() == "true":
            try:
                websocket_token = await self._websocket_token(client_id, device_id)
            except Exception:
                logger.exception("WebSocket token generation failed")
        if is_blank(websocket_url) or websocket_url == "null":
            selected_websocket = "ws://xiaozhi.server.com:8000/xiaozhi/v1/"
        else:
            websocket_urls = _java_semicolon_split(websocket_url or "")
            selected_websocket = (
                random.choice(websocket_urls)  # noqa: S311
                if websocket_urls
                else "ws://xiaozhi.server.com:8000/xiaozhi/v1/"
            )
        response["websocket"] = {"url": selected_websocket, "token": websocket_token}

        mqtt_endpoint = await self.params.get_value("server.mqtt_gateway", from_cache=True)
        if mqtt_endpoint not in (None, "", "null"):
            try:
                group_id = str(device.get("board") or "GID_default") if device is not None else "GID_default"
                mqtt = await self._mqtt_config(device_id, group_id, client_ip)
                if mqtt is not None:
                    mqtt["endpoint"] = mqtt_endpoint
                    response["mqtt"] = mqtt
            except Exception:
                logger.exception("MQTT credential generation failed")

        if device is None:
            response["activation"] = await self._activation(device_id, report)
        else:
            app_version = report.application.version if report.application is not None else None
            agent_id = device.get("agent_id")
            normalized_agent_id = None if agent_id is None else str(agent_id)
            if defer_connection_update is not None:
                defer_connection_update(str(device["id"]), normalized_agent_id, app_version)
            else:
                try:
                    await self._persist_connection_update(
                        str(device["id"]),
                        normalized_agent_id,
                        app_version,
                    )
                except Exception:
                    logger.exception("Asynchronous device connection update failed")
        return cast(dict[str, Any], self._drop_none(response))

    async def _persist_connection_update(
        self,
        device_id: str,
        agent_id: str | None,
        app_version: str | None,
    ) -> None:
        connection_time = shanghai_now_naive()
        try:
            await self.repository.update_connection(device_id, app_version=app_version, now=connection_time)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        if not is_blank(agent_id):
            await redis_set(f"agent:device:lastConnected:{agent_id}", connection_time, client=self.redis)

    @staticmethod
    async def persist_connection_update_background(
        device_id: str,
        agent_id: str | None,
        app_version: str | None,
    ) -> None:
        try:
            async with get_session_factory()() as session:
                await DeviceService(session)._persist_connection_update(device_id, agent_id, app_version)
        except Exception:
            logger.exception("Asynchronous device connection update failed")

    async def ota_health_text(self) -> str:
        mqtt_gateway = await self.params.get_value("server.mqtt_gateway", from_cache=False)
        if is_blank(mqtt_gateway):
            return "OTA接口不正常，缺少mqtt_gateway地址，请登录智控台，在参数管理找到【server.mqtt_gateway】配置"
        websocket = await self.params.get_value("server.websocket", from_cache=True)
        if is_blank(websocket) or websocket == "null":
            return "OTA接口不正常，缺少websocket地址，请登录智控台，在参数管理找到【server.websocket】配置"
        ota_url = await self.params.get_value("server.ota", from_cache=True)
        if is_blank(ota_url) or ota_url == "null":
            return "OTA接口不正常，缺少ota地址，请登录智控台，在参数管理找到【server.ota】配置"
        return f"OTA接口运行正常，websocket集群数量：{len(_java_semicolon_split(websocket or ''))}"

    async def ota_page(self, query: Mapping[str, Any]) -> dict[str, Any]:
        page = self._positive_int(query.get("page"), 1)
        limit = self._positive_int(query.get("limit"), 10)
        requested = query.get("orderField")
        requested_fields = [requested] if isinstance(requested, str) else list(requested or [])
        fields = [OTA_ORDER_COLUMNS[field] for field in requested_fields if field in OTA_ORDER_COLUMNS]
        if not fields:
            fields = ["update_date"]
        ascending = str(query.get("order") or "").lower() == "asc" if requested_fields else True
        firmware_name = query.get("firmwareName")
        name = str(firmware_name) if firmware_name is not None else None
        rows = await self.repository.list_ota(
            page=page,
            limit=limit,
            firmware_name=name,
            order_fields=fields,
            ascending=ascending,
        )
        rows = [self._ota_response_record(row) for row in rows]
        return {"total": await self.repository.count_ota(name), "list": rows}

    async def get_ota_record(self, ota_id: str) -> dict[str, Any] | None:
        row = await self.repository.get_ota(ota_id)
        return None if row is None else self._ota_response_record(row)

    async def save_ota(self, record: OtaRecord, user: AuthUser) -> None:
        values = record.model_dump(by_alias=False)
        existing = await self.repository.get_first_ota_by_type(record.type or "")
        now = shanghai_now_naive()
        if existing is not None:
            values["updater"] = record.updater if record.updater is not None else user.id
            values["update_date"] = record.update_date if record.update_date is not None else now
            await self.repository.update_ota(str(existing["id"]), values)
        else:
            values["id"] = record.id or uuid.uuid4().hex
            values["creator"] = record.creator if record.creator is not None else user.id
            values["updater"] = record.updater if record.updater is not None else user.id
            values["create_date"] = record.create_date if record.create_date is not None else now
            values["update_date"] = record.update_date if record.update_date is not None else now
            await self.repository.insert_ota(values)
        await self.session.commit()

    async def update_ota(self, ota_id: str, record: OtaRecord, user: AuthUser) -> None:
        if await self.repository.count_duplicate_ota(
            ota_id=ota_id,
            ota_type=record.type,
            version=record.version,
        ):
            raise RuntimeError("已存在相同类型和版本的固件，请修改后重试")
        values = record.model_dump(by_alias=False)
        values["updater"] = record.updater if record.updater is not None else user.id
        values["update_date"] = shanghai_now_naive()
        await self.repository.update_ota(ota_id, values)
        await self.session.commit()

    async def delete_ota(self, ids: Sequence[str]) -> None:
        await self.repository.delete_ota(ids)
        await self.session.commit()

    async def create_ota_download_id(self, ota_id: str) -> str:
        value = str(uuid.uuid4())
        await redis_set(f"ota:id:{value}", ota_id, client=self.redis)
        return value

    async def resolve_ota_download(self, download_id: str) -> tuple[Path, str] | None:
        id_key = f"ota:id:{download_id}"
        ota_value = await redis_get(id_key, self.redis)
        if is_blank(None if ota_value is None else str(ota_value)):
            return None
        count_key = f"ota:download:count:{download_id}"
        count_value = await redis_get(count_key, self.redis)
        count = int(count_value or 0)
        if count >= 3:
            await redis_delete(count_key, id_key, client=self.redis)
            return None
        await redis_set(count_key, count + 1, client=self.redis)

        ota_id = str(ota_value)
        if ota_id.startswith("file:"):
            firmware_path = ota_id[5:]
            ota_type = "assets"
            version = "1.0.0"
        else:
            record = await self.repository.get_ota(ota_id)
            firmware_value = None if record is None else record.get("firmware_path")
            if record is None or is_blank(None if firmware_value is None else str(firmware_value)):
                return None
            firmware_path = str(record["firmware_path"])
            ota_type = str(record.get("type"))
            version = str(record.get("version"))
        raw_path = Path(firmware_path)
        candidates = [raw_path] if raw_path.is_absolute() else [Path.cwd() / raw_path]
        if not raw_path.is_absolute() and raw_path.parts and raw_path.parts[0] == "uploadfile":
            candidates.insert(0, get_settings().upload_dir.joinpath(*raw_path.parts[1:]))
        candidates.append(Path.cwd() / "firmware" / raw_path.name)
        resolved = next((candidate for candidate in candidates if candidate.is_file()), None)
        if resolved is None:
            return None
        original_name = f"{ota_type}_{version}"
        dot_index = firmware_path.rfind(".")
        if dot_index >= 0:
            original_name += firmware_path[dot_index:]
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", original_name)
        return resolved, safe_name

    async def save_firmware_file(self, *, filename: str | None, content: bytes) -> str:
        if not content:
            raise ValueError("上传文件不能为空")
        if filename is None:
            raise ValueError("文件名不能为空")
        dot_index = filename.rfind(".")
        if dot_index < 0:
            raise RuntimeError("文件名缺少扩展名")
        extension = filename[dot_index:].lower()
        if extension not in {".bin", ".apk"}:
            raise ValueError("只允许上传.bin和.apk格式的文件")
        digest = hashlib.md5(content, usedforsecurity=False).hexdigest()
        directory = get_settings().upload_dir
        directory.mkdir(parents=True, exist_ok=True)
        filename_on_disk = f"{digest}{extension}"
        physical_path = directory / filename_on_disk
        if not physical_path.exists():
            with physical_path.open("xb") as stream:
                stream.write(content)
        # Keep Java's database/API value stable even when the physical upload
        # volume is mounted elsewhere (for example /data/uploads in Docker).
        return str(Path("uploadfile") / filename_on_disk)

    async def save_assets_file(self, *, filename: str | None, content: bytes, user: AuthUser) -> str:
        ota_url = await self.params.get_value("server.ota", from_cache=True)
        if is_blank(ota_url) or ota_url == "null":
            raise AppError(10102)
        if len(content) > 20 * 1024 * 1024:
            raise AppError(10142)
        if not user.is_super_admin:
            count_key = f"ota:upload:count:{user.id}"
            current = int(await redis_get(count_key, self.redis) or 0)
            if current >= 50:
                raise AppError(10195)
            await redis_increment(count_key, client=self.redis)
        path = await self.save_firmware_file(filename=filename, content=content)
        download_id = await self.create_ota_download_id(f"file:{path}")
        return (ota_url or "").replace("/ota/", "/otaMag/download/") + download_id

    async def _gateway_device(self, device_id: str, user: AuthUser) -> tuple[str, dict[str, Any]] | None:
        gateway = await self.params.get_value("server.mqtt_manager_api", from_cache=True)
        if is_blank(gateway) or gateway == "null":
            return None
        device = await self.repository.get_device(device_id)
        if device is None or int(device.get("user_id") or -1) != user.id:
            return None
        return gateway or "", device

    async def _post_gateway(self, url: str, body: Any, *, timeout_seconds: float | None = None) -> str:
        key = await self.params.get_value("server.mqtt_signature_key", from_cache=False)
        return await post_json(
            url,
            body,
            key or "",
            timeout_seconds=timeout_seconds or get_settings().external_request_timeout_seconds,
            client=self.http_client,
        )

    async def _post_call(self, path: str, body: dict[str, Any], action: str) -> dict[str, Any]:
        gateway = await self.params.get_value("server.mqtt_manager_api", from_cache=True)
        key = await self.params.get_value("server.mqtt_signature_key", from_cache=True)
        if is_blank(gateway) or gateway == "null" or is_blank(key) or (key or "").strip().lower() == "null":
            return {"status": "error", "message": f"{action}失败，网关配置缺失"}
        result: dict[str, Any] = {"status": "error"}
        try:
            text = await post_json(
                f"http://{gateway}{path}",
                body,
                key or "",
                timeout_seconds=5.0,
                client=self.http_client,
            )
            if text.strip():
                payload = json.loads(text)
                if isinstance(payload, dict):
                    result["status"] = payload.get("status")
                    result["message"] = payload.get("message")
            return result
        except Exception:
            return {"status": "error", "message": f"{action}失败，请稍后再试"}

    async def _firmware_info(
        self,
        ota_type: str | None,
        current_version: str | None,
        request_url: str,
    ) -> dict[str, Any] | None:
        if is_blank(ota_type):
            return None
        selected_version = current_version if not is_blank(current_version) else "0.0.0"
        ota = await self.repository.get_latest_ota(ota_type or "")
        download_url: str | None = None
        if ota is not None and self._compare_versions(ota.get("version"), selected_version) > 0:
            ota_url = await self.params.get_value("server.ota", from_cache=True)
            if is_blank(ota_url) or ota_url == "null":
                ota_url = request_url
            download_id = await self.create_ota_download_id(str(ota["id"]))
            download_url = (ota_url or "").replace("/ota/", "/otaMag/download/") + download_id
        return {
            "version": selected_version if ota is None else ota.get("version"),
            "url": download_url or INVALID_FIRMWARE_URL,
        }

    async def _activation(self, device_id: str, report: DeviceReportRequest) -> dict[str, Any]:
        safe_device_id = device_id.replace(":", "_").lower()
        data_key = f"ota:activation:data:{safe_device_id}"
        cached = _mapping(await redis_get(data_key, self.redis))
        code = str(cached.get("activation_code")) if cached and cached.get("activation_code") is not None else None
        frontend = await self.params.get_value("server.fronted_url", from_cache=True)
        if code is None or not code.strip():
            code = f"{secrets.randbelow(1_000_000):06d}"
            board = (
                report.board.type
                if report.board is not None and report.board.type is not None
                else (report.chip_model_name or "unknown")
            )
            app_version = report.application.version if report.application is not None else None
            await redis_set(
                data_key,
                {
                    "id": device_id,
                    "mac_address": device_id,
                    "board": board,
                    "app_version": app_version,
                    "deviceId": device_id,
                    "activation_code": code,
                },
                client=self.redis,
            )
            await redis_set(f"ota:activation:code:{code}", device_id, client=self.redis)
        return {
            "code": code,
            "message": f"{frontend if frontend is not None else 'null'}\n{code}",
            "challenge": device_id,
        }

    async def _websocket_token(self, client_id: str, username: str) -> str:
        secret = await self.params.get_value("server.secret", from_cache=False)
        if is_blank(secret):
            raise RuntimeError("WebSocket认证密钥未配置(server.secret)")
        timestamp = int(datetime.now().timestamp())
        message = f"{client_id}|{username}|{timestamp}".encode()
        signature = hmac.new((secret or "").encode(), message, hashlib.sha256).digest()
        encoded = base64.urlsafe_b64encode(signature).decode().rstrip("=")
        return f"{encoded}.{timestamp}"

    async def _mqtt_config(self, mac_address: str, group_id: str, client_ip: str) -> dict[str, Any] | None:
        key = await self.params.get_value("server.mqtt_signature_key", from_cache=True)
        if is_blank(key):
            return None
        client_id = self._mqtt_client_id(group_id, mac_address)
        user_data = json.dumps({"ip": client_ip}, ensure_ascii=False, separators=(",", ":"))
        username = base64.b64encode(user_data.encode()).decode()
        password = base64.b64encode(
            hmac.new((key or "").encode(), f"{client_id}|{username}".encode(), hashlib.sha256).digest()
        ).decode()
        safe_mac = mac_address.replace(":", "_")
        return {
            "client_id": client_id,
            "username": username,
            "password": password,
            "publish_topic": "device-server",
            "subscribe_topic": f"devices/p2p/{safe_mac}",
        }

    @staticmethod
    def _mqtt_client_id(group_id: str, mac_address: str) -> str:
        safe_group = group_id.replace(":", "_")
        safe_mac = mac_address.replace(":", "_")
        return f"{safe_group}@@@{safe_mac}@@@{safe_mac}"

    @staticmethod
    def _compare_versions(first: Any, second: Any) -> int:
        if first is None or second is None:
            return 0
        first = str(first)
        second = str(second)
        first_parts = first.split(".")
        second_parts = second.split(".")
        for index in range(max(len(first_parts), len(second_parts))):
            first_value = int(first_parts[index]) if index < len(first_parts) else 0
            second_value = int(second_parts[index]) if index < len(second_parts) else 0
            if first_value != second_value:
                return 1 if first_value > second_value else -1
        return 0

    async def _unique_alias(self, mac_address: str, alias: str | None) -> str | None:
        existing = await self.repository.get_aliases(mac_address)
        if alias not in existing:
            return alias
        suffix = 1
        while f"{alias}{suffix}" in existing:
            suffix += 1
        return f"{alias}{suffix}"

    @staticmethod
    def _mac_device_name(mac: str) -> str:
        return mac if len(mac) < 2 else f"尾号为{mac[-2:]}的设备"

    @staticmethod
    def _positive_int(value: Any, default: int) -> int:
        if value is None:
            return default
        return int(str(value))

    @staticmethod
    def _drop_none(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: DeviceService._drop_none(item) for key, item in value.items() if item is not None}
        if isinstance(value, list):
            return [DeviceService._drop_none(item) for item in value]
        return value

    @staticmethod
    def _user_device_view(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "app_version": row.get("app_version"),
            "bind_user_name": None,
            "device_type": row.get("board"),
            "board": row.get("board"),
            "id": row.get("id"),
            "mac_address": row.get("mac_address"),
            "alias": row.get("alias"),
            "ota_upgrade": None,
            "recent_chat_time": None,
            "last_connected_at_timestamp": DeviceService._timestamp(row.get("last_connected_at")),
            "create_date_timestamp": DeviceService._timestamp(row.get("create_date")),
            # UserShowDeviceListVO pins only this field to UTC.  The companion
            # epoch value still uses the configured Asia/Shanghai instant.
            "create_date": DeviceService._utc_datetime(row.get("create_date")),
        }

    @staticmethod
    def _utc_datetime(value: Any) -> Any:
        if not isinstance(value, datetime):
            return value
        localized = value.replace(tzinfo=ZoneInfo(get_settings().timezone)) if value.tzinfo is None else value
        return localized.astimezone(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _ota_response_record(row: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(row)
        if result.get("size") is not None:
            result["size"] = str(result["size"])
        return result

    @staticmethod
    def _timestamp(value: Any) -> int | None:
        if not isinstance(value, datetime):
            return None
        localized = value.replace(tzinfo=ZoneInfo(get_settings().timezone)) if value.tzinfo is None else value
        return int(localized.timestamp() * 1000)
