from __future__ import annotations

import hashlib
import json
from datetime import datetime

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError

from app.core.crypto import bcrypt_hash, bcrypt_matches, generate_database_token
from app.core.errors import ErrorCode
from app.core.i18n import message_for, resolve_language
from app.core.ids import SnowflakeIdGenerator
from app.core.redis import JavaRedisCodec
from app.core.responses import JavaJSONResponse, envelope, error_response
from app.core.serialization import java_compatible, preserve_java_map_keys
from app.main import validation_error_handler


def test_java_response_envelope_always_contains_null_data() -> None:
    response = JavaJSONResponse(envelope(code=401, msg="Unauthorized"))
    assert json.loads(response.body) == {"code": 401, "msg": "Unauthorized", "data": None}


def test_auth_filter_can_preserve_java_content_type_without_starlette_charset_rewrite() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/xiaozhi/user/info", "headers": []})
    response = error_response(request, 401, media_type="application/json;charset=utf-8")
    assert response.headers["content-type"] == "application/json;charset=utf-8"


@pytest.mark.asyncio
async def test_absent_request_body_uses_java_generic_error_but_field_missing_uses_10034() -> None:
    request = Request({"type": "http", "method": "POST", "path": "/xiaozhi/user/login", "headers": []})
    absent = RequestValidationError(
        [{"type": "missing", "loc": ("body",), "msg": "Field required", "input": None}]
    )
    absent_response = await validation_error_handler(request, absent)
    assert json.loads(absent_response.body) == {
        "code": ErrorCode.INTERNAL_SERVER_ERROR,
        "msg": "服务器内部异常",
        "data": None,
    }

    field_missing = RequestValidationError(
        [{"type": "missing", "loc": ("body", "username"), "msg": "Field required", "input": {}}]
    )
    field_response = await validation_error_handler(request, field_missing)
    assert json.loads(field_response.body) == {
        "code": ErrorCode.PARAM_VALUE_NULL,
        "msg": "Field required",
        "data": None,
    }


@pytest.mark.asyncio
async def test_java_binding_failures_use_generic_error_without_changing_json_field_validation() -> None:
    root_type_request = Request(
        {"type": "http", "method": "POST", "path": "/xiaozhi/admin/dict/data/delete", "headers": []}
    )
    root_type = RequestValidationError(
        [{"type": "list_type", "loc": ("body",), "msg": "Input should be a valid list", "input": {}}]
    )
    root_response = await validation_error_handler(root_type_request, root_type)
    assert json.loads(root_response.body) == {
        "code": ErrorCode.INTERNAL_SERVER_ERROR,
        "msg": "服务器内部异常",
        "data": None,
    }

    query_request = Request(
        {"type": "http", "method": "GET", "path": "/xiaozhi/models/list", "headers": []}
    )
    missing_query = RequestValidationError(
        [{"type": "missing", "loc": ("query", "modelType"), "msg": "Field required", "input": None}]
    )
    query_response = await validation_error_handler(query_request, missing_query)
    assert json.loads(query_response.body)["code"] == ErrorCode.INTERNAL_SERVER_ERROR

    multipart_request = Request(
        {"type": "http", "method": "POST", "path": "/xiaozhi/voiceClone/upload", "headers": []}
    )
    missing_file = RequestValidationError(
        [{"type": "missing", "loc": ("body", "file"), "msg": "Field required", "input": None}]
    )
    multipart_response = await validation_error_handler(multipart_request, missing_file)
    assert json.loads(multipart_response.body)["code"] == ErrorCode.INTERNAL_SERVER_ERROR

    json_request = Request(
        {"type": "http", "method": "POST", "path": "/xiaozhi/unmapped-json", "headers": []}
    )
    missing_field = RequestValidationError(
        [{"type": "missing", "loc": ("body", "name"), "msg": "Field required", "input": {}}]
    )
    json_response = await validation_error_handler(json_request, missing_field)
    assert json.loads(json_response.body) == {
        "code": ErrorCode.PARAM_VALUE_NULL,
        "msg": "Field required",
        "data": None,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "field", "expected"),
    [
        ("/xiaozhi/admin/server/emit-action", "action", "操作不能为空"),
        ("/xiaozhi/admin/server/emit-action", "targetWs", "目标ws地址不能为空"),
        ("/xiaozhi/agent", "agentName", "智能体名称不能为空"),
        ("/xiaozhi/agent/chat-history/report", "macAddress", "不能为空"),
        (
            "/xiaozhi/agent/missing/snapshots/missing/restore",
            "currentStateToken",
            "不能为空",
        ),
        ("/xiaozhi/config/agent-models", "macAddress", "设备MAC地址不能为空"),
        ("/xiaozhi/config/agent-models", "clientId", "客户端ID不能为空"),
        (
            "/xiaozhi/config/agent-models",
            "selectedModule",
            "客户端已实例化的模型不能为空",
        ),
        ("/xiaozhi/config/correct-words", "macAddress", "设备MAC地址不能为空"),
        ("/xiaozhi/device/address-book/alias", "targetMac", "目标MAC地址不能为空"),
        ("/xiaozhi/device/address-book/alias", "macAddress", "MAC地址不能为空"),
    ],
)
async def test_required_json_fields_keep_java_constraint_messages(
    path: str, field: str, expected: str
) -> None:
    request = Request({"type": "http", "method": "POST", "path": path, "headers": []})
    missing = RequestValidationError(
        [{"type": "missing", "loc": ("body", field), "msg": "Field required", "input": {}}]
    )
    response = await validation_error_handler(request, missing)
    assert json.loads(response.body) == {
        "code": ErrorCode.PARAM_VALUE_NULL,
        "msg": expected,
        "data": None,
    }


def test_dynamic_java_map_keys_are_not_changed_by_property_naming() -> None:
    response = JavaJSONResponse(
        envelope(
            preserve_java_map_keys(
                {"selected_module": {"wake_up_words": ["你好"]}, "timestamp": 2**32}
            )
        )
    )
    assert json.loads(response.body)["data"] == {
        "selected_module": {"wake_up_words": ["你好"]},
        "timestamp": str(2**32),
    }


def test_long_dates_aliases_and_nulls_follow_jackson_configuration() -> None:
    payload = java_compatible(
        {
            "id": 7,
            "agent_id": 1890000000000000000,
            "word_count": 3,
            "created_at": datetime(2026, 7, 20, 9, 8, 7),
            "optional_value": None,
        }
    )
    assert payload == {
        "id": "7",
        "agentId": "1890000000000000000",
        "wordCount": 3,
        "createdAt": "2026-07-20 09:08:07",
        "optionalValue": None,
    }
    # PageData.total is declared as an Integer in the Java baseline, not a Long.
    assert java_compatible({"total": 1}) == {"total": 1}


def test_accept_language_uses_first_value_and_supported_fallbacks() -> None:
    assert resolve_language("de-DE;q=0.1,en-US;q=1") == "de-DE"
    assert message_for(401, "zh-CN") == "未授权"
    assert message_for(401, "zh-TW") == "未授權"
    assert message_for(401, "en") == "Unauthorized"
    assert message_for(401, "de") == "Nicht autorisiert"
    assert message_for(401, "vi") == "Không được ủy quyền"
    assert message_for(401, "pt-BR") == "Não autorizado"
    assert message_for(401, "unknown") == "未授权"


def test_java_redis_json_wire_format_for_protocol_scalars() -> None:
    assert JavaRedisCodec.encode("abc") == b'"abc"'
    assert JavaRedisCodec.encode(3) == b"3"
    assert JavaRedisCodec.encode(["a", "b"]) == b'["java.util.ArrayList",["a","b"]]'
    assert JavaRedisCodec.encode({"nested": {"enabled": True}}) == (
        b'{"@class":"java.util.HashMap","nested":{"@class":"java.util.HashMap","enabled":true}}'
    )
    assert JavaRedisCodec.encode(2147483648) == b"2147483648"
    assert JavaRedisCodec.encode({"number": 2147483648}) == (
        b'{"@class":"java.util.HashMap","number":["java.lang.Long",2147483648]}'
    )
    assert JavaRedisCodec.decode(b'["java.util.ArrayList",["a","b"]]') == ["a", "b"]
    assert JavaRedisCodec.decode(b'"abc"') == "abc"
    assert JavaRedisCodec.decode(b"legacy-unquoted") == "legacy-unquoted"


def test_database_token_is_java_md5_uuid_format() -> None:
    expected = hashlib.md5(b"fixed-input", usedforsecurity=False).hexdigest()
    assert generate_database_token("fixed-input") == expected
    generated = generate_database_token()
    assert len(generated) == 32
    assert generated == generated.lower()


def test_bcrypt_output_is_accepted_by_bundled_java_encoder() -> None:
    encoded = bcrypt_hash("correct horse battery staple")
    assert encoded.startswith("$2a$10$")
    assert bcrypt_matches("correct horse battery staple", encoded)
    assert not bcrypt_matches("wrong", encoded)
    assert not bcrypt_matches("correct horse battery staple", encoded.replace("$2a$", "$2b$", 1))


def test_snowflake_ids_are_unique_monotonic_and_fit_signed_bigint() -> None:
    generator = SnowflakeIdGenerator(worker_id=1, datacenter_id=2)
    values = [generator.next_id() for _ in range(1000)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)
    assert all(0 < value < 2**63 for value in values)
