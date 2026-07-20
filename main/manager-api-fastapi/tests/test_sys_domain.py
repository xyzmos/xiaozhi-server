from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from websockets.asyncio.server import serve

from app.core.crypto import bcrypt_matches
from app.core.errors import AppError
from app.core.redis import JavaRedisCodec
from app.core.security import AuthUser
from app.repositories.sys import SysRepository
from app.routers.sys import sys_router
from app.schemas.sys import DictDataPayload, DictTypePayload, EmitServerActionRequest, SysParamPayload
from app.services.sys import AdminService, DictService, ParamExternalValidator, ServerActionService, SysParamService
from tests.domain_support import FakeRedis, sqlite_session

SYS_SCHEMA = [
    "CREATE TABLE sys_user ("
    "id INTEGER PRIMARY KEY, username TEXT, password TEXT, super_admin INTEGER, status INTEGER, "
    "creator INTEGER, create_date DATETIME, updater INTEGER, update_date DATETIME)",
    "CREATE TABLE ai_device ("
    "id INTEGER PRIMARY KEY, user_id INTEGER, mac_address TEXT, last_connected_at DATETIME, auto_update INTEGER, "
    "board TEXT, alias TEXT, agent_id TEXT, app_version TEXT, sort INTEGER, create_date DATETIME, "
    "update_date DATETIME)",
    "CREATE TABLE sys_params ("
    "id INTEGER PRIMARY KEY, param_code TEXT UNIQUE, param_value TEXT, value_type TEXT, param_type INTEGER, "
    "remark TEXT, creator INTEGER, create_date DATETIME, updater INTEGER, update_date DATETIME)",
    "CREATE TABLE ai_agent_plugin_mapping (id INTEGER PRIMARY KEY, agent_id TEXT, plugin_id TEXT)",
    "CREATE TABLE sys_dict_type ("
    "id INTEGER PRIMARY KEY, dict_type TEXT UNIQUE, dict_name TEXT, remark TEXT, sort INTEGER, "
    "creator INTEGER, create_date DATETIME, updater INTEGER, update_date DATETIME)",
    "CREATE TABLE sys_dict_data ("
    "id INTEGER PRIMARY KEY, dict_type_id INTEGER, dict_label TEXT, dict_value TEXT, remark TEXT, sort INTEGER, "
    "creator INTEGER, create_date DATETIME, updater INTEGER, update_date DATETIME)",
]


ADMIN = AuthUser(7, "root", 1, 1, "token", {})


@pytest.mark.asyncio
async def test_admin_param_update_external_mock_menu_side_effect_and_cache() -> None:
    redis = FakeRedis()
    calls: list[str] = []

    async def endpoint(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="xiaozhi OTA service")

    async with sqlite_session(SYS_SCHEMA) as session, httpx.AsyncClient(
        transport=httpx.MockTransport(endpoint)
    ) as client:
        await session.execute(
            text(
                "INSERT INTO sys_params "
                "(id, param_code, param_value, value_type, param_type) VALUES "
                "(1, 'server.ota', 'https://old.example/ota/', 'string', 1),"
                "(2, 'system-web.menu', :menu, 'json', 1)"
            ),
            {"menu": json.dumps({"features": {"addressBook": {"enabled": True}}})},
        )
        await session.execute(
            text(
                "INSERT INTO ai_agent_plugin_mapping (id, agent_id, plugin_id) "
                "VALUES (10, 'agent-1', 'SYSTEM_PLUGIN_CALL_DEVICE')"
            )
        )
        await session.execute(
            text(
                "INSERT INTO sys_user (id, username, status, super_admin) VALUES "
                "(7, 'root', 1, 1), (8, 'member', 1, 0)"
            )
        )
        await session.execute(
            text(
                "INSERT INTO ai_device "
                "(id, user_id, mac_address, board, alias, app_version, create_date, update_date) "
                "VALUES (20, 8, 'AA:BB', 'esp32s3', 'Kitchen', '1.0.0', "
                "'2026-01-02 03:04:05', CURRENT_TIMESTAMP)"
            )
        )
        await session.commit()

        params = SysParamService(
            SysRepository(session),
            redis=redis,  # type: ignore[arg-type]
            validator=ParamExternalValidator(client),
        )
        await params.update(
            SysParamPayload(
                id=1,
                param_code="server.ota",
                param_value="https://mock.example/ota/",
                value_type="string",
            ),
            ADMIN,
        )
        assert calls == ["https://mock.example/ota/"]
        assert await params.get_value("server.ota") == "https://mock.example/ota/"
        assert 0 < await redis.ttl("sys:params") <= 86400

        await params.update(
            SysParamPayload(
                id=2,
                param_code="system-web.menu",
                param_value=json.dumps({"features": {"addressBook": {"enabled": False}}}),
                value_type="json",
            ),
            ADMIN,
        )
        remaining = await session.scalar(
            text("SELECT COUNT(*) FROM ai_agent_plugin_mapping WHERE plugin_id = 'SYSTEM_PLUGIN_CALL_DEVICE'")
        )
        assert remaining == 0

        # Missing `features` does not mean disabled in Java: both feature maps
        # must be present before it removes call-device mappings.
        await session.execute(
            text("UPDATE sys_params SET param_value = :menu WHERE id = 2"),
            {"menu": json.dumps({"features": {"addressBook": {"enabled": True}}})},
        )
        await session.execute(
            text(
                "INSERT INTO ai_agent_plugin_mapping (id, agent_id, plugin_id) "
                "VALUES (11, 'agent-1', 'SYSTEM_PLUGIN_CALL_DEVICE')"
            )
        )
        await session.commit()
        await params.update(
            SysParamPayload(id=2, param_code="system-web.menu", param_value="{}", value_type="json"),
            ADMIN,
        )
        assert await session.scalar(text("SELECT COUNT(*) FROM ai_agent_plugin_mapping WHERE id = 11")) == 1

        with pytest.raises(AppError) as add_group:
            await params.save(
                SysParamPayload(
                    id=99,
                    param_code="new.param",
                    param_value="value",
                    value_type="string",
                ),
                ADMIN,
                "en-US",
            )
        assert add_group.value.code == 500
        assert add_group.value.message == "ID has to be empty"

        with pytest.raises(AppError) as update_group:
            await params.update(
                SysParamPayload(param_code="new.param", param_value="value", value_type="string"),
                ADMIN,
                "de-DE",
            )
        assert update_group.value.code == 500
        assert update_group.value.message == "ID darf nicht leer sein"

        with pytest.raises(AppError) as value_type_pattern:
            await params.update(
                SysParamPayload(id=1, param_code="server.ota", param_value="value", value_type="STRING"),
                ADMIN,
                "en-US",
            )
        assert value_type_pattern.value.code == 500
        assert value_type_pattern.value.message == "Value type must be string, number, boolean or array"

        admin = AdminService(SysRepository(session))
        users = await admin.page_users(mobile="mem", page=1, limit=10)
        assert users["total"] == 1
        assert users["list"][0]["deviceCount"] == "1"
        zero_limit_users = await admin.page_users(mobile="mem", page=1, limit=0)
        assert zero_limit_users == {"list": [], "total": 1}
        generated = await admin.reset_password(8, ADMIN)
        stored = await session.scalar(text("SELECT password FROM sys_user WHERE id = 8"))
        assert len(generated) == 12 and bcrypt_matches(generated, stored)
        assert await session.scalar(text("SELECT updater FROM sys_user WHERE id = 8")) == ADMIN.id
        devices = await admin.page_devices(keywords="Kit", page=1, limit=10)
        assert devices["list"][0]["createDate"] == "2026-01-01 19:04:05"

        with pytest.raises(ValueError):
            await admin.change_status(0, ["8", "not-a-long"], ADMIN)
        assert await session.scalar(text("SELECT status FROM sys_user WHERE id = 8")) == 1


@pytest.mark.asyncio
async def test_dict_crud_preserves_java_duplicate_rule_and_invalidates_cache() -> None:
    redis = FakeRedis()
    async with sqlite_session(SYS_SCHEMA) as session:
        await session.execute(text("INSERT INTO sys_user (id, username, status, super_admin) VALUES (7, 'root', 1, 1)"))
        await session.execute(
            text(
                "INSERT INTO sys_dict_type "
                "(id, dict_type, dict_name, sort, creator, updater) VALUES (1, 'MOBILE_AREA', 'Area', 1, 7, 7)"
            )
        )
        await session.commit()
        service = DictService(SysRepository(session), redis=redis)  # type: ignore[arg-type]

        await service.save_type(
            DictTypePayload(id=99, dict_type="CUSTOM", dict_name="Custom", sort=-1),
            ADMIN,
        )
        custom_sort = await session.scalar(text("SELECT sort FROM sys_dict_type WHERE id = 99"))
        assert custom_sort == -1

        await service.save_data(
            DictDataPayload(dict_type_id=1, dict_label="China", dict_value="+86", sort=1),
            ADMIN,
        )
        row = (await session.execute(text("SELECT id FROM sys_dict_data"))).scalar_one()
        assert await service.items("MOBILE_AREA") == [{"name": "China", "key": "+86"}]
        cached_items = json.loads((await redis.get("sys:dict:data:MOBILE_AREA")).decode())
        assert cached_items[0] == "java.util.ArrayList"
        assert cached_items[1][0]["@class"] == "xiaozhi.modules.sys.vo.SysDictDataItem"

        await service.update_data(DictDataPayload(id=row, dict_value="+1"), ADMIN)
        partially_updated = (
            await session.execute(
                text("SELECT dict_type_id, dict_label, dict_value FROM sys_dict_data WHERE id = :id"),
                {"id": row},
            )
        ).mappings().one()
        assert dict(partially_updated) == {"dict_type_id": 1, "dict_label": "China", "dict_value": "+1"}
        # Java cannot derive the real cache key without dictTypeId and therefore leaves this stale entry in place.
        assert await service.items("MOBILE_AREA") == [{"name": "China", "key": "+86"}]

        await service.update_data(
            DictDataPayload(id=row, dict_type_id=1, dict_label="China mainland", dict_value="+86", sort=2),
            ADMIN,
        )
        assert await redis.get("sys:dict:data:MOBILE_AREA") is None

        # SysDictDataServiceImpl compares dictValue to the existing dictLabel; this intentionally tests that quirk.
        with pytest.raises(AppError) as captured:
            await service.save_data(
                DictDataPayload(dict_type_id=1, dict_label="Unrelated", dict_value="China mainland", sort=3),
                ADMIN,
            )
        assert captured.value.code == 10128


@pytest.mark.asyncio
async def test_server_action_websocket_hmac_headers_payload_and_one_time_registration() -> None:
    redis = FakeRedis()
    captured: dict[str, Any] = {}

    async def handler(websocket: Any) -> None:
        captured["headers"] = dict(websocket.request.headers)
        captured["payload"] = json.loads(await websocket.recv())
        await websocket.send(json.dumps({"status": "success", "type": "server", "content": {"action": "done"}}))

    async with serve(handler, "127.0.0.1", 0) as server:
        socket = server.sockets[0]
        port = socket.getsockname()[1]
        websocket_url = f"ws://127.0.0.1:{port}/xiaozhi/v1/"
        async with sqlite_session(SYS_SCHEMA) as session:
            await session.execute(
                text(
                    "INSERT INTO sys_params "
                    "(id, param_code, param_value, value_type, param_type) VALUES "
                    "(1, 'server.websocket', :url, 'string', 1),"
                    "(2, 'server.secret', 'local-test-secret', 'string', 1)"
                ),
                {"url": websocket_url + ";;"},
            )
            await session.commit()
            param_service = SysParamService(SysRepository(session), redis=redis)  # type: ignore[arg-type]
            assert await ServerActionService(param_service, redis=redis).server_list() == [websocket_url]  # type: ignore[arg-type]
            result = await ServerActionService(param_service, redis=redis).emit(  # type: ignore[arg-type]
                EmitServerActionRequest(target_ws=websocket_url, action="RESTART")
            )
            assert result is True

    headers = captured["headers"]
    device_id = headers["device-id"]
    client_id = headers["client-id"]
    token, timestamp_text = headers["authorization"].removeprefix("Bearer ").rsplit(".", 1)
    expected = hmac.new(
        b"local-test-secret",
        f"{client_id}|{device_id}|{timestamp_text}".encode(),
        digestmod=hashlib.sha256,
    ).digest()
    assert token == base64.urlsafe_b64encode(expected).rstrip(b"=").decode()
    assert captured["payload"] == {
        "type": "server",
        "action": "restart",
        "content": {"secret": "local-test-secret"},
    }
    assert JavaRedisCodec.decode(await redis.get(f"tmp_register_mac:{device_id}")) == "true"
    assert 0 < await redis.ttl(f"tmp_register_mac:{device_id}") <= 300

    with pytest.raises(AppError) as empty_urls:
        await ParamExternalValidator().validate("server.websocket", ";")
    assert empty_urls.value.code == 10098


def test_sys_router_exposes_all_seven_controller_groups() -> None:
    routes = {(method, route.path) for route in sys_router.routes for method in route.methods}
    assert len(routes) == 23
    assert ("GET", "/admin/users") in routes
    assert ("POST", "/admin/server/emit-action") in routes
    assert ("POST", "/admin/params/delete") in routes
    assert ("GET", "/admin/dict/data/type/{dict_type}") in routes
