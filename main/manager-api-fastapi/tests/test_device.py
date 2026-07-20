from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI, Request
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.database import get_db
from app.core.security import AuthUser
from app.integrations.mqtt_gateway import daily_authorization_tokens, post_json
from app.routers.device import _validate_device_update, device_router, unbind_device, update_address_alias
from app.schemas.device import (
    ApplicationInfo,
    BoardInfo,
    DeviceAddressBookAliasRequest,
    DeviceManualAddRequest,
    DeviceReportRequest,
    DeviceUnbindRequest,
    DeviceUpdateRequest,
)
from app.services.device import DeviceService, redis_get, redis_set
from app.services.system_params import SystemParamService
from tests.domain_support import FakeRedis, sqlite_session

DEVICE_SCHEMA = [
    """
    CREATE TABLE ai_device (
      id VARCHAR(32) PRIMARY KEY, user_id BIGINT, mac_address VARCHAR(50), last_connected_at DATETIME,
      auto_update INTEGER, board VARCHAR(50), alias VARCHAR(64), agent_id VARCHAR(32), app_version VARCHAR(20),
      sort INTEGER, updater BIGINT, update_date DATETIME, creator BIGINT, create_date DATETIME
    )
    """,
    """
    CREATE TABLE ai_ota (
      id VARCHAR(32) PRIMARY KEY, firmware_name VARCHAR(100), type VARCHAR(50), version VARCHAR(50), size BIGINT,
      remark VARCHAR(500), firmware_path VARCHAR(255), sort INTEGER, updater BIGINT, update_date DATETIME,
      creator BIGINT, create_date DATETIME
    )
    """,
    """
    CREATE TABLE ai_device_address_book (
      mac_address VARCHAR(64), target_mac VARCHAR(64), alias VARCHAR(64), has_permission INTEGER,
      creator BIGINT, create_date DATETIME, updater BIGINT, update_date DATETIME,
      PRIMARY KEY (mac_address, target_mac)
    )
    """,
    "CREATE TABLE sys_params (param_code VARCHAR(100) PRIMARY KEY, param_value TEXT, update_date DATETIME)",
]


def normal_user(user_id: int = 7, *, super_admin: int = 0) -> AuthUser:
    return AuthUser(
        id=user_id,
        username="tester",
        super_admin=super_admin,
        status=1,
        token="test-token",  # noqa: S106 - isolated authentication fixture
        row={"id": user_id},
    )


def test_device_router_closes_all_assigned_paths_and_static_routes_win() -> None:
    routes = [route for route in device_router.routes if hasattr(route, "methods")]
    pairs = {(next(iter(route.methods)), route.path) for route in routes}
    assert pairs == {
        ("POST", "/device/bind/{agent_id}/{device_code}"),
        ("POST", "/device/register"),
        ("GET", "/device/bind/{agent_id}"),
        ("POST", "/device/bind/{agent_id}"),
        ("POST", "/device/unbind"),
        ("PUT", "/device/update/{device_id}"),
        ("PUT", "/user/configDevice/{device_id}"),
        ("POST", "/device/manual-add"),
        ("POST", "/device/tools/list/{device_id}"),
        ("POST", "/device/tools/call/{device_id}"),
        ("GET", "/device/address-book/call"),
        ("GET", "/device/address-book/lookup"),
        ("PUT", "/device/address-book/alias"),
        ("PUT", "/device/address-book/permission"),
        ("GET", "/device/address-book/{mac_address}"),
        ("POST", "/ota/"),
        ("POST", "/ota/activate"),
        ("GET", "/ota/"),
        ("GET", "/otaMag/getDownloadUrl/{ota_id}"),
        ("GET", "/otaMag/download/{download_id}"),
        ("POST", "/otaMag/upload"),
        ("POST", "/otaMag/uploadAssetsBin"),
        ("GET", "/otaMag"),
        ("GET", "/otaMag/{ota_id}"),
        ("POST", "/otaMag"),
        ("DELETE", "/otaMag/{ota_id}"),
        ("PUT", "/otaMag/{ota_id}"),
    }
    assert len(routes) == len(pairs)
    paths = [route.path for route in routes]
    assert paths.index("/device/address-book/call") < paths.index("/device/address-book/{mac_address}")
    assert paths.index("/otaMag/getDownloadUrl/{ota_id}") < paths.index("/otaMag/{ota_id}")


def test_device_update_validation_matches_java_utf16_and_localized_constraints() -> None:
    assert _validate_device_update(DeviceUpdateRequest(alias="😀" * 32), "en-US") is None
    assert (
        _validate_device_update(DeviceUpdateRequest(alias="😀" * 33), "en-US")
        == "size must be between 0 and 64"
    )
    assert _validate_device_update(DeviceUpdateRequest(auto_update=2), "de-DE") == "muss kleiner-gleich 1 sein"


@pytest.mark.asyncio
async def test_unbind_empty_object_is_java_successful_noop_and_alias_validates_target_first() -> None:
    async with sqlite_session(DEVICE_SCHEMA) as session:
        request = Request({"type": "http", "method": "POST", "path": "/device/unbind", "headers": []})
        request.state.user = normal_user()
        response = await unbind_device(DeviceUnbindRequest(), request, session)
        assert json.loads(response.body) == {"code": 0, "msg": "success", "data": None}

        alias_request = Request(
            {"type": "http", "method": "PUT", "path": "/device/address-book/alias", "headers": []}
        )
        alias_request.state.user = normal_user()
        alias_response = await update_address_alias(
            DeviceAddressBookAliasRequest(), alias_request, session
        )
        assert json.loads(alias_response.body) == {
            "code": 10034,
            "msg": "目标MAC地址不能为空",
            "data": None,
        }


def test_device_list_keeps_java_utc_create_date_but_shanghai_epoch() -> None:
    view = DeviceService._user_device_view(  # noqa: SLF001 - compatibility regression fixture
        {
            "id": "device",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "create_date": datetime(2026, 7, 20, 12, 34, 56),
        }
    )
    assert view["create_date"] == datetime(2026, 7, 20, 4, 34, 56)
    assert view["create_date_timestamp"] == 1_784_522_096_000


@pytest.mark.asyncio
async def test_mqtt_gateway_uses_java_daily_tokens_and_only_retries_401() -> None:
    fixed = datetime(2026, 7, 20, 1, 2, 3, tzinfo=timezone.utc)
    tokens = daily_authorization_tokens("shared-key", fixed)
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Authorization"])
        assert json.loads(request.content) == {"clientIds": ["one"]}
        return httpx.Response(401 if len(seen) < 3 else 200, text='{"success":true}')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await post_json(
            "http://gateway/api/devices/status",
            {"clientIds": ["one"]},
            "shared-key",
            timeout_seconds=1,
            now=fixed,
            client=client,
        )
    assert result == '{"success":true}'
    assert seen == [f"Bearer {token}" for token in tokens]


@pytest.mark.asyncio
async def test_device_activation_commits_row_and_consumes_java_redis_keys() -> None:
    fake = cast(Redis, FakeRedis())
    device_id = "AA:BB:CC:DD:EE:FF"
    code = "123456"
    await redis_set(f"ota:activation:code:{code}", device_id, client=fake)
    await redis_set(
        "ota:activation:data:aa_bb_cc_dd_ee_ff",
        {
            "activation_code": code,
            "mac_address": device_id,
            "board": "esp32-s3",
            "app_version": "1.2.3",
        },
        client=fake,
    )
    async with sqlite_session(DEVICE_SCHEMA) as session:
        service = DeviceService(session, redis_client=fake)
        await service.activate_bound_device(agent_id="agent-1", activation_code=code, user=normal_user())
        row = (
            await session.execute(text("SELECT * FROM ai_device WHERE id = :id"), {"id": device_id})
        ).mappings().one()
        assert row["user_id"] == 7
        assert row["agent_id"] == "agent-1"
        assert row["auto_update"] == 1
    assert await redis_get(f"ota:activation:code:{code}", fake) is None
    assert await redis_get("ota:activation:data:aa_bb_cc_dd_ee_ff", fake) is None


@pytest.mark.asyncio
async def test_manual_add_preserves_java_uuid_fill_for_missing_mac() -> None:
    fake = cast(Redis, FakeRedis())
    await redis_set("agent:device:count:null", 4, client=fake)
    async with sqlite_session(DEVICE_SCHEMA) as session:
        await DeviceService(session, redis_client=fake).manual_add(
            request=DeviceManualAddRequest(),
            user=normal_user(),
        )
        row = (await session.execute(text("SELECT id,mac_address FROM ai_device"))).mappings().one()
    assert len(row["id"]) == 32
    assert row["mac_address"] is None
    assert await redis_get("agent:device:count:null", fake) is None


@pytest.mark.asyncio
async def test_domain_redis_maps_use_spring_json_type_metadata() -> None:
    fake = cast(Redis, FakeRedis())
    await redis_set("map", {"outer": {"value": "ok"}}, client=fake)
    raw = await cast(Any, fake).get("map")
    assert json.loads(raw) == {
        "@class": "java.util.HashMap",
        "outer": {"@class": "java.util.HashMap", "value": "ok"},
    }
    assert await redis_get("map", fake) == {"outer": {"value": "ok"}}


@pytest.mark.asyncio
async def test_ota_report_keeps_numeric_timestamp_signatures_and_activation_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = cast(Redis, FakeRedis())
    params = {
        "server.websocket": "ws://one/xiaozhi/v1/",
        "server.auth.enabled": "true",
        "server.secret": "ws-secret",
        "server.mqtt_gateway": "mqtt.example:1883",
        "server.mqtt_signature_key": "mqtt-secret",
        "server.fronted_url": "https://console.example",
    }

    async def get_value(_: SystemParamService, code: str, *, from_cache: bool = True) -> str | None:
        del from_cache
        return params.get(code)

    monkeypatch.setattr(SystemParamService, "get_value", get_value)
    report = DeviceReportRequest(
        application=ApplicationInfo(version="1.0.0"),
        board=BoardInfo(type="esp32-s3"),
    )
    async with sqlite_session(DEVICE_SCHEMA) as session:
        payload = await DeviceService(session, redis_client=fake).check_ota(
            device_id="AA:BB:CC:DD:EE:FF",
            client_id="client-one",
            report=report,
            request_url="http://manager/xiaozhi/ota/",
            client_ip="127.0.0.1",
        )
    assert isinstance(payload["server_time"]["timestamp"], int)
    assert payload["firmware"]["url"].endswith("NOT_ACTIVATED_FIRMWARE_THIS_IS_A_INVALID_URL")
    assert payload["activation"]["challenge"] == "AA:BB:CC:DD:EE:FF"
    websocket_signature, websocket_timestamp = payload["websocket"]["token"].split(".")
    assert websocket_signature
    assert websocket_timestamp.isdigit()
    mqtt = payload["mqtt"]
    decoded_user = json.loads(__import__("base64").b64decode(mqtt["username"]))
    assert decoded_user == {"ip": "127.0.0.1"}
    assert mqtt["client_id"] == "GID_default@@@AA_BB_CC_DD_EE_FF@@@AA_BB_CC_DD_EE_FF"
    activation_key = "ota:activation:data:aa_bb_cc_dd_ee_ff"
    assert 86_390 <= await cast(Any, fake).ttl(activation_key) <= 86_400


@pytest.mark.asyncio
async def test_address_book_lookup_matches_historical_server_consumer_contract() -> None:
    fake = cast(Redis, FakeRedis())
    now = "2026-07-20 10:00:00"
    async with sqlite_session(DEVICE_SCHEMA) as session:
        await session.execute(
            text(
                "INSERT INTO ai_device_address_book "
                "(mac_address,target_mac,alias,has_permission,create_date,update_date) "
                "VALUES (:a,:b,'小明',1,:now,:now),(:b,:a,'客厅',1,:now,:now)"
            ),
            {"a": "AA:AA:AA:AA:AA:AA", "b": "BB:BB:BB:BB:BB:BB", "now": now},
        )
        await session.commit()
        service = DeviceService(session, redis_client=fake)
        await service.refresh_address_book_cache()
        result = await service.lookup_address_book(caller_mac="AA:AA:AA:AA:AA:AA", nickname="小明")
    assert result == {
        "targetMac": "bb:bb:bb:bb:bb:bb",
        "callerNickname": "客厅",
        "hasPermission": "true",
    }


@pytest.mark.asyncio
async def test_firmware_storage_md5_and_three_download_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    fake = cast(Redis, FakeRedis())
    content = b"firmware-bytes"
    expected = f"uploadfile/{hashlib.md5(content, usedforsecurity=False).hexdigest()}.bin"
    async with sqlite_session(DEVICE_SCHEMA) as session:
        service = DeviceService(session, redis_client=fake)
        stored = await service.save_firmware_file(filename="release.bin", content=content)
        assert stored == expected
        assert Path(stored).read_bytes() == content
        await redis_set("ota:id:download", f"file:{stored}", client=fake)
        for _ in range(3):
            resolved = await service.resolve_ota_download("download")
            assert resolved is not None
            assert resolved[0].read_bytes() == content
            assert resolved[1] == "assets_1.0.0.bin"
        assert await service.resolve_ota_download("download") is None
    assert await redis_get("ota:id:download", fake) is None


@pytest.mark.asyncio
async def test_firmware_download_route_preserves_binary_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    fake = cast(Redis, FakeRedis())
    firmware = tmp_path / "release.bin"
    firmware.write_bytes(b"binary-firmware")
    await redis_set("ota:id:route-link", f"file:{firmware}", client=fake)
    monkeypatch.setattr("app.services.device.get_redis", lambda: fake)
    async with sqlite_session(DEVICE_SCHEMA) as session:
        app = FastAPI()
        app.include_router(device_router)

        async def override_db() -> Any:
            yield session

        app.dependency_overrides[get_db] = override_db
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/otaMag/download/route-link")
    assert response.status_code == 200
    assert response.content == b"binary-firmware"
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-length"] == str(len(response.content))
    assert response.headers["content-disposition"] == 'attachment; filename="assets_1.0.0.bin"'
