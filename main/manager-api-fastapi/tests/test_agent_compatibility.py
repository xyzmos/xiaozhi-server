from __future__ import annotations

import copy
import json
import subprocess
from collections.abc import Awaitable
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote_plus

import httpx
import pytest
import respx
from fastapi import Request
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import AppError
from app.core.redis import JavaRedisCodec
from app.core.responses import error_response
from app.core.security import AuthUser
from app.integrations.llm import openai_completion
from app.integrations.mcp import build_agent_mcp_address, encrypt_agent_token
from app.integrations.voiceprint import VoicePrintClient, VoicePrintEndpoint, VoicePrintIntegrationError
from app.repositories.agent import AgentRepository
from app.routers.agent import router
from app.routers.agent import update_template as update_template_route
from app.schemas.agent import (
    AgentChatHistoryReport,
    AgentCreate,
    AgentSnapshotPage,
    AgentSnapshotRestore,
    AgentTemplate,
    AgentUpdate,
    FunctionInfo,
)
from app.services.agent import (
    SECRET_PLACEHOLDER,
    AgentService,
    _cached_datetime,
    _changed_snapshot_fields,
    _parse_snapshot_data,
    _preserve_snapshot_sensitive,
    _redact_snapshot_data,
    _snapshot_state_token,
)
from tests.domain_support import sqlite_session

TARGET_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = TARGET_ROOT.parents[1]
JAVA_BIN = REPOSITORY_ROOT / ".runtime" / "jdk" / "bin"
MCP_VECTOR_PATH = TARGET_ROOT / "tests" / "fixtures" / "agent-mcp-aes-golden.json"

EXPECTED_AGENT_ROUTES = {
    ("POST", "/agent/chat-history/report"),
    ("POST", "/agent/chat-history/getDownloadUrl/{agentId}/{sessionId}"),
    ("GET", "/agent/chat-history/download/{uuid}/current"),
    ("GET", "/agent/chat-history/download/{uuid}/previous"),
    ("GET", "/agent/template/page"),
    ("POST", "/agent/template/batch-remove"),
    ("GET", "/agent/template/{id}"),
    ("POST", "/agent/template"),
    ("PUT", "/agent/template"),
    ("DELETE", "/agent/template/{id}"),
    ("POST", "/agent/voice-print"),
    ("PUT", "/agent/voice-print"),
    ("DELETE", "/agent/voice-print/{id}"),
    ("GET", "/agent/voice-print/list/{id}"),
    ("GET", "/agent/mcp/address/{agentId}"),
    ("GET", "/agent/mcp/tools/{agentId}"),
    ("GET", "/agent/tag/list"),
    ("POST", "/agent/tag"),
    ("DELETE", "/agent/tag/{id}"),
    ("POST", "/agent/audio/{audioId}"),
    ("GET", "/agent/play/{uuid}"),
    ("PUT", "/agent/saveMemory/{macAddress}"),
    ("POST", "/agent/chat-summary/{sessionId}/save"),
    ("POST", "/agent/chat-title/{sessionId}/generate"),
    ("GET", "/agent/all"),
    ("GET", "/agent/list"),
    ("GET", "/agent/template"),
    ("GET", "/agent/{agentId}/snapshots"),
    ("GET", "/agent/{agentId}/snapshots/{snapshotId}"),
    ("POST", "/agent/{agentId}/snapshots/{snapshotId}/restore"),
    ("DELETE", "/agent/{agentId}/snapshots/{snapshotId}"),
    ("GET", "/agent/{id}/sessions"),
    ("GET", "/agent/{id}/chat-history/{sessionId}"),
    ("GET", "/agent/{id}/chat-history/user"),
    ("GET", "/agent/{id}/chat-history/audio"),
    ("GET", "/agent/{id}/tags"),
    ("PUT", "/agent/{id}/tags"),
    ("POST", "/agent"),
    ("PUT", "/agent/{id}"),
    ("DELETE", "/agent/{id}"),
    ("GET", "/agent/{id}"),
}

AGENT_SCHEMA = [
    """
    CREATE TABLE ai_agent (
      id TEXT PRIMARY KEY, user_id INTEGER, agent_code TEXT, agent_name TEXT, asr_model_id TEXT,
      vad_model_id TEXT, llm_model_id TEXT, slm_model_id TEXT, vllm_model_id TEXT, tts_model_id TEXT,
      tts_voice_id TEXT, tts_language TEXT, tts_volume INTEGER, tts_rate INTEGER, tts_pitch INTEGER,
      mem_model_id TEXT, intent_model_id TEXT, chat_history_conf INTEGER, system_prompt TEXT,
      summary_memory TEXT, lang_code TEXT, language TEXT, sort INTEGER, creator INTEGER, created_at DATETIME,
      updater INTEGER, updated_at DATETIME
    )
    """,
    """
    CREATE TABLE ai_agent_template (
      id TEXT PRIMARY KEY, agent_code TEXT, agent_name TEXT, asr_model_id TEXT, vad_model_id TEXT,
      llm_model_id TEXT, vllm_model_id TEXT, tts_model_id TEXT, tts_voice_id TEXT, tts_language TEXT,
      tts_volume INTEGER, tts_rate INTEGER, tts_pitch INTEGER, mem_model_id TEXT, intent_model_id TEXT,
      chat_history_conf INTEGER, system_prompt TEXT, summary_memory TEXT, lang_code TEXT, language TEXT,
      sort INTEGER, creator INTEGER, created_at DATETIME, updater INTEGER, updated_at DATETIME
    )
    """,
    """
    CREATE TABLE ai_model_config (
      id TEXT PRIMARY KEY, model_type TEXT, model_code TEXT, model_name TEXT, is_default INTEGER,
      is_enabled INTEGER, config_json TEXT, sort INTEGER
    )
    """,
    "CREATE TABLE ai_model_provider (id TEXT PRIMARY KEY, provider_code TEXT, fields TEXT)",
    "CREATE TABLE ai_tts_voice (id TEXT PRIMARY KEY, tts_model_id TEXT, tts_voice TEXT, name TEXT, languages TEXT)",
    "CREATE TABLE ai_voice_clone (id TEXT PRIMARY KEY, name TEXT, languages TEXT)",
    """
    CREATE TABLE ai_agent_plugin_mapping (
      id INTEGER PRIMARY KEY, agent_id TEXT, plugin_id TEXT, param_info TEXT, UNIQUE(agent_id, plugin_id)
    )
    """,
    """
    CREATE TABLE ai_agent_context_provider (
      id TEXT PRIMARY KEY, agent_id TEXT, context_providers TEXT, creator INTEGER, created_at DATETIME,
      updater INTEGER, updated_at DATETIME
    )
    """,
    """
    CREATE TABLE ai_agent_correct_word_mapping (
      id TEXT PRIMARY KEY, agent_id TEXT, file_id TEXT, creator INTEGER, created_at DATETIME,
      updater INTEGER, updated_at DATETIME, UNIQUE(agent_id, file_id)
    )
    """,
    """
    CREATE TABLE ai_agent_tag (
      id TEXT PRIMARY KEY, tag_name TEXT, sort INTEGER, deleted INTEGER, creator INTEGER,
      created_at DATETIME, updater INTEGER, updated_at DATETIME
    )
    """,
    """
    CREATE TABLE ai_agent_tag_relation (
      id TEXT PRIMARY KEY, agent_id TEXT, tag_id TEXT, sort INTEGER, creator INTEGER,
      created_at DATETIME, updater INTEGER, updated_at DATETIME
    )
    """,
    """
    CREATE TABLE ai_agent_snapshot (
      id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, user_id INTEGER, version_no INTEGER NOT NULL,
      snapshot_data TEXT NOT NULL, changed_fields TEXT, source TEXT, restore_from_snapshot_id TEXT,
      restore_from_version_no INTEGER, creator INTEGER, created_at DATETIME, redaction_version INTEGER,
      UNIQUE(agent_id, version_no)
    )
    """,
    """
    CREATE TABLE ai_device (
      id TEXT PRIMARY KEY, user_id INTEGER, mac_address TEXT, agent_id TEXT, last_connected_at DATETIME
    )
    """,
    "CREATE TABLE ai_device_address_book (mac_address TEXT, target_mac TEXT)",
    """
    CREATE TABLE ai_agent_chat_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT, mac_address TEXT, agent_id TEXT, session_id TEXT,
      chat_type INTEGER, content TEXT, audio_id TEXT, created_at DATETIME
    )
    """,
    """
    CREATE TABLE ai_agent_chat_title (
      id TEXT PRIMARY KEY, session_id TEXT, title TEXT, created_at DATETIME, updated_at DATETIME
    )
    """,
    "CREATE TABLE ai_agent_chat_audio (id TEXT PRIMARY KEY, audio BLOB)",
]


def normal_user(user_id: int = 7) -> AuthUser:
    return AuthUser(
        id=user_id,
        username="agent-user",
        super_admin=0,
        status=1,
        token="test-token",  # noqa: S106 - isolated authentication fixture
        row={"id": user_id},
    )


async def java_error_payload(awaitable: Awaitable[Any]) -> dict[str, Any]:
    with pytest.raises(AppError) as captured:
        await awaitable
    request = Request({"type": "http", "method": "GET", "path": "/agent/test", "headers": []})
    payload = json.loads(bytes(error_response(request, captured.value.code, captured.value.message).body))
    assert isinstance(payload, dict)
    return cast(dict[str, Any], payload)


@pytest.fixture(scope="module")
def mcp_vectors() -> list[dict[str, str]]:
    value = json.loads(MCP_VECTOR_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, list)
    return value


@pytest.fixture(scope="module")
def java_mcp_classpath(tmp_path_factory: pytest.TempPathFactory) -> Path:
    classes = tmp_path_factory.mktemp("agent-mcp-java")
    subprocess.run(  # noqa: S603
        [
            str(JAVA_BIN / "javac"),
            "-d",
            str(classes),
            str(
                REPOSITORY_ROOT
                / "main"
                / "manager-api"
                / "src"
                / "main"
                / "java"
                / "xiaozhi"
                / "common"
                / "utils"
                / "AESUtils.java"
            ),
            str(TARGET_ROOT / "tests" / "java" / "AgentMcpCryptoInteropCli.java"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return classes


def test_agent_router_matches_all_six_java_controllers() -> None:
    routes = [cast(APIRoute, route) for route in router.routes]
    actual = {
        (method, route.path)
        for route in routes
        for method in sorted(getattr(route, "methods", set()) or set())
    }
    assert actual == EXPECTED_AGENT_ROUTES
    assert len(actual) == 41

    paths = [route.path for route in routes]
    assert paths.index("/agent/template/page") < paths.index("/agent/template/{id}")
    assert paths.index("/agent/list") < paths.index("/agent/{id}")
    assert paths.index("/agent/{agentId}/snapshots") < paths.index("/agent/{id}")
    assert paths.index("/agent/{id}/chat-history/user") < paths.index("/agent/{id}/chat-history/{sessionId}")
    assert paths.index("/agent/{id}/chat-history/audio") < paths.index("/agent/{id}/chat-history/{sessionId}")


@pytest.mark.parametrize(
    ("model", "payload", "message"),
    [
        (AgentCreate, {"agentName": "  "}, "智能体名称不能为空"),
        (
            AgentChatHistoryReport,
            {"macAddress": " ", "sessionId": "session", "chatType": 1, "content": "content"},
            "不能为空",
        ),
        (
            AgentChatHistoryReport,
            {"macAddress": "mac", "sessionId": "session", "chatType": None, "content": "content"},
            "不能为空",
        ),
        (AgentSnapshotRestore, {"currentStateToken": ""}, "不能为空"),
    ],
)
def test_agent_not_blank_constraints_keep_java_messages(
    model: type[Any], payload: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError) as captured:
        model.model_validate(payload)
    assert captured.value.errors()[0]["msg"] == message


@pytest.mark.asyncio
async def test_agent_missing_record_permission_and_validation_order_match_java() -> None:
    missing = "contract-missing-agent"
    snapshot_error = {"code": 500, "msg": "没有权限访问该智能体快照", "data": None}
    permission_error = {"code": 10169, "msg": "您没有权限操作该记录", "data": None}

    async with sqlite_session(AGENT_SCHEMA) as session:
        service = AgentService(session, normal_user())

        assert await java_error_payload(service.snapshot_page(missing, AgentSnapshotPage())) == snapshot_error
        assert await java_error_payload(service.snapshot_detail(missing, "missing-snapshot")) == snapshot_error
        assert await java_error_payload(
            service.restore_snapshot(missing, "missing-snapshot", "valid-state-token")
        ) == snapshot_error
        assert await java_error_payload(service.delete_snapshot(missing, "missing-snapshot")) == snapshot_error

        assert await java_error_payload(service.sessions(missing, None, None)) == permission_error
        assert await java_error_payload(service.audio_content("missing-audio")) == permission_error
        assert await java_error_payload(service.agent_tags(missing)) == permission_error
        assert await java_error_payload(service.save_agent_tags(missing, None, None)) == permission_error

        await session.execute(
            text("INSERT INTO ai_agent (id,user_id,agent_name) VALUES ('owned-agent',7,'Owned')")
        )
        await session.commit()
        assert await java_error_payload(service.sessions("owned-agent", None, None)) == {
            "code": 500,
            "msg": "服务器内部异常",
            "data": None,
        }
        assert await java_error_payload(service.sessions("owned-agent", "bad", "10")) == {
            "code": 500,
            "msg": "服务器内部异常",
            "data": None,
        }
        assert await service.sessions("owned-agent", "1", "10") == {"list": [], "total": 0}


@pytest.mark.asyncio
async def test_template_update_without_id_keeps_java_generic_error() -> None:
    request = Request({"type": "http", "method": "PUT", "path": "/agent/template", "headers": []})
    async with sqlite_session(AGENT_SCHEMA) as session:
        response = await update_template_route(AgentTemplate(), request, session, normal_user())
    assert json.loads(bytes(response.body)) == {"code": 500, "msg": "服务器内部异常", "data": None}


def test_mcp_tokens_match_static_and_live_java_golden_vectors(
    mcp_vectors: list[dict[str, str]], java_mcp_classpath: Path
) -> None:
    for vector in mcp_vectors:
        python_token = encrypt_agent_token(vector["agentId"], vector["key"])
        java_token = subprocess.run(  # noqa: S603
            [
                str(JAVA_BIN / "java"),
                "-cp",
                str(java_mcp_classpath),
                "AgentMcpCryptoInteropCli",
                vector["agentId"],
                vector["key"],
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert python_token == vector["token"]
        assert java_token == vector["token"]


def test_mcp_address_preserves_java_path_scheme_and_form_encoding(mcp_vectors: list[dict[str, str]]) -> None:
    vector = mcp_vectors[0]
    endpoint = f"https://broker.example/xiaozhi/v1/?key={vector['key']}"
    assert build_agent_mcp_address(endpoint, vector["agentId"]) == (
        f"wss://broker.example/xiaozhi/v1/mcp/?token={quote_plus(vector['token'], safe='')}"
    )
    assert build_agent_mcp_address("null", vector["agentId"]) is None


def _snapshot_fixture() -> dict[str, Any]:
    return {
        "agentCode": "AGT_1",
        "agentName": "agent",
        "summaryMemory": None,
        "functions": [
            {
                "pluginId": "plugin-a",
                "paramInfo": {
                    "apiKey": "function-secret",
                    "safe": "visible",
                    "nested": {"password": "nested-secret"},
                    "webhookUrl": "https://hooks.slack.com/services/T/B/slack-secret?key=query-secret&safe=1",
                },
            }
        ],
        "contextProviders": [
            {
                "url": "https://user:pass@example.com/context?api_key=url-secret&safe=1#token=fragment-secret",
                "headers": {"Authorization": "Bearer header-secret", "X-Safe": "visible"},
            }
        ],
        "correctWordFileIds": ["file-b", "file-a"],
        "tagNames": ["tag-b", "tag-a"],
        "tags": [{"id": "tag-id", "tagName": "tag-a", "sort": 0}],
    }


def test_snapshot_redaction_is_secret_free_and_reversible() -> None:
    current = _parse_snapshot_data(_snapshot_fixture())
    assert current is not None
    redacted = _redact_snapshot_data(current)
    assert redacted is not None
    wire = json.dumps(redacted, ensure_ascii=False)
    for secret in (
        "function-secret",
        "nested-secret",
        "slack-secret",
        "query-secret",
        "user:pass",
        "url-secret",
        "fragment-secret",
        "header-secret",
    ):
        assert secret not in wire
    assert wire.count(SECRET_PLACEHOLDER) >= 8
    assert "safe=1" in wire
    assert "visible" in wire

    restored = _preserve_snapshot_sensitive(redacted, current)
    assert restored == current


def test_snapshot_state_token_and_change_detection_match_java_normalization() -> None:
    first = _parse_snapshot_data(_snapshot_fixture())
    assert first is not None
    second = copy.deepcopy(first)
    second["functions"][0]["paramInfo"]["apiKey"] = "rotated-function-secret"
    second["contextProviders"][0]["headers"]["Authorization"] = "Bearer rotated-header-secret"
    second["correctWordFileIds"].reverse()
    second["tagNames"].reverse()
    second["summaryMemory"] = "   "
    assert _snapshot_state_token(first) == _snapshot_state_token(second)
    assert _changed_snapshot_fields(first, second) == []

    second["agentName"] = "changed"
    assert _changed_snapshot_fields(first, second) == ["agentName"]


def test_snapshot_url_redaction_keeps_public_parameters_and_rejects_cross_origin_restore() -> None:
    current = _parse_snapshot_data(_snapshot_fixture())
    assert current is not None
    redacted = _redact_snapshot_data(current)
    assert redacted is not None
    provider = redacted["contextProviders"][0]
    assert provider["url"] == (
        f"https://{SECRET_PLACEHOLDER}@example.com/context?api_key={SECRET_PLACEHOLDER}&safe=1"
        f"#token={SECRET_PLACEHOLDER}"
    )

    provider["url"] = provider["url"].replace("example.com", "attacker.example")
    with pytest.raises(Exception, match="URL 标识"):
        _preserve_snapshot_sensitive(redacted, current)


def test_function_info_accepts_java_string_or_map_param_info() -> None:
    from_string = FunctionInfo.model_validate({"pluginId": "p", "paramInfo": '{"answer":42}'})
    from_map = FunctionInfo.model_validate({"pluginId": "p", "paramInfo": {"answer": 42}})
    assert from_string.param_info == from_map.param_info == {"answer": 42}


def test_java_date_redis_wire_round_trip() -> None:
    value = datetime(2026, 7, 20, 12, 34, 56, 789000)
    encoded = JavaRedisCodec.encode(value)
    assert json.loads(encoded) == ["java.util.Date", 1784522096789]
    assert _cached_datetime(JavaRedisCodec.decode(encoded)) == value


@pytest.mark.asyncio
async def test_snapshot_repository_allocates_monotonic_versions_and_prunes() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TABLE ai_agent_snapshot ("
                "id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, user_id INTEGER, version_no INTEGER NOT NULL,"
                "snapshot_data TEXT NOT NULL, changed_fields TEXT, source TEXT, restore_from_snapshot_id TEXT,"
                "restore_from_version_no INTEGER, creator INTEGER, created_at DATETIME, redaction_version INTEGER,"
                "UNIQUE(agent_id, version_no))"
            )
        )
    async with factory() as session:
        repository = AgentRepository(session)
        for index in range(1, 5):
            assert (
                await repository.insert_snapshot_next_version(
                    {
                        "id": f"snapshot-{index}",
                        "agent_id": "agent",
                        "user_id": 1,
                        "snapshot_data": "{}",
                        "changed_fields": "[]",
                        "source": "config",
                        "restore_from_snapshot_id": None,
                        "restore_from_version_no": None,
                        "creator": 1,
                        "created_at": datetime(2026, 7, 20, 12, index),
                        "redaction_version": 2,
                    }
                )
                == 1
            )
        assert await repository.snapshot_max_version("agent") == 4
        assert await repository.prune_snapshots("agent", 2) == 2
        rows = await repository.fetch_all(
            "SELECT id,version_no FROM ai_agent_snapshot WHERE agent_id=:id ORDER BY version_no", {"id": "agent"}
        )
        assert rows == [{"id": "snapshot-3", "version_no": 3}, {"id": "snapshot-4", "version_no": 4}]
    await engine.dispose()


@pytest.mark.asyncio
async def test_agent_create_update_restore_rollback_and_delete_are_transactional() -> None:
    async with sqlite_session(AGENT_SCHEMA) as session:
        await session.execute(
            text(
                "INSERT INTO ai_agent_template "
                "(id,agent_name,llm_model_id,mem_model_id,system_prompt,summary_memory,lang_code,language,sort) "
                "VALUES ('template','默认模板','llm-default','Memory_local_short','默认提示词','初始记忆',"
                "'zh_CN','中文',1)"
            )
        )
        await session.execute(
            text(
                "INSERT INTO ai_model_config "
                "(id,model_type,model_name,is_default,is_enabled,config_json,sort) "
                "VALUES ('llm-default','LLM','默认模型',1,1,:config,1)"
            ),
            {
                "config": json.dumps(
                    {
                        "type": "openai",
                        "base_url": "https://llm.invalid/v1",
                        "api_key": "mock-only",
                        "model_name": "mock",
                    }
                )
            },
        )
        for provider_id in ("SYSTEM_PLUGIN_MUSIC", "SYSTEM_PLUGIN_WEATHER", "SYSTEM_PLUGIN_NEWS_NEWSNOW"):
            await session.execute(
                text("INSERT INTO ai_model_provider (id,provider_code,fields) VALUES (:id,:id,:fields)"),
                {
                    "id": provider_id,
                    "fields": json.dumps([{"key": "region", "default": "cn"}]),
                },
            )
        await session.commit()

        service = AgentService(session, normal_user())
        agent_id = await service.create_agent(AgentCreate(agent_name="测试智能体"))
        detail = await service.agent_detail(agent_id)
        assert detail["agent_name"] == "测试智能体"
        assert detail["chat_history_conf"] == 2
        assert detail["current_version_no"] == 1
        assert {item["plugin_id"] for item in detail["functions"]} == {
            "SYSTEM_PLUGIN_MUSIC",
            "SYSTEM_PLUGIN_WEATHER",
            "SYSTEM_PLUGIN_NEWS_NEWSNOW",
        }

        await service.update_agent(
            agent_id,
            AgentUpdate.model_validate(
                {
                    "agentName": "更新后的智能体",
                    "functions": [{"pluginId": "SYSTEM_PLUGIN_WEATHER", "paramInfo": {"region": "shanghai"}}],
                    "contextProviders": [{"url": "https://context.example/v1", "headers": {"X-Safe": "yes"}}],
                    "correctWordFileIds": ["words-1"],
                    "tagNames": ["家庭"],
                }
            ),
        )
        updated = await service.agent_detail(agent_id)
        assert updated["agent_name"] == "更新后的智能体"
        assert [item["plugin_id"] for item in updated["functions"]] == ["SYSTEM_PLUGIN_WEATHER"]
        assert updated["context_providers"] == [
            {"url": "https://context.example/v1", "headers": {"X-Safe": "yes"}}
        ]
        assert updated["correct_word_file_ids"] == ["words-1"]
        assert updated["current_version_no"] == 2
        assigned_tags = await service.agent_tags(agent_id)
        assert len(assigned_tags) == 1
        assert assigned_tags[0]["tagName"] == "家庭"

        snapshot_rows = await service.repo.fetch_all(
            "SELECT id,version_no,source FROM ai_agent_snapshot WHERE agent_id=:id ORDER BY version_no",
            {"id": agent_id},
        )
        assert [(row["version_no"], row["source"]) for row in snapshot_rows] == [(1, "initial"), (2, "config")]

        with pytest.raises(AppError):
            await service.update_agent(
                agent_id,
                AgentUpdate.model_validate(
                    {"agentName": "不应提交", "llmModelId": "missing-model", "functions": []}
                ),
            )
        after_rollback = await service.agent_detail(agent_id)
        assert after_rollback["agent_name"] == "更新后的智能体"
        assert [item["plugin_id"] for item in after_rollback["functions"]] == ["SYSTEM_PLUGIN_WEATHER"]
        assert after_rollback["current_version_no"] == 2

        first_snapshot = snapshot_rows[0]
        preview = await service.snapshot_detail(agent_id, str(first_snapshot["id"]))
        await service.restore_snapshot(agent_id, str(first_snapshot["id"]), str(preview["currentStateToken"]))
        restored = await service.agent_detail(agent_id)
        assert restored["agent_name"] == "测试智能体"
        assert restored["current_version_no"] == 3
        assert {item["plugin_id"] for item in restored["functions"]} == {
            "SYSTEM_PLUGIN_MUSIC",
            "SYSTEM_PLUGIN_WEATHER",
            "SYSTEM_PLUGIN_NEWS_NEWSNOW",
        }
        assert await service.agent_tags(agent_id) == []
        assert await service.repo.scalar("SELECT COUNT(*) FROM ai_agent_tag") == 1

        await service.delete_agent(agent_id)
        assert await service.repo.get_agent(agent_id) is None
        assert await service.repo.scalar(
            "SELECT COUNT(*) FROM ai_agent_snapshot WHERE agent_id=:id", {"id": agent_id}
        ) == 0
        assert await service.repo.scalar("SELECT COUNT(*) FROM ai_agent_tag") == 1


@pytest.mark.asyncio
async def test_voiceprint_mock_validates_java_multipart_and_error_mapping() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = await request.aread()
        if request.url.path == "/voiceprint/identify":
            assert b'name="speaker_ids"' in body
            assert b"speaker-a,speaker-b" in body
            assert b'filename="VoicePrint.WAV"' in body
            return httpx.Response(200, json={"speaker_id": "speaker-a", "score": 0.75})
        if request.url.path == "/voiceprint/register":
            assert b'name="speaker_id"' in body
            return httpx.Response(200, text="true")
        return httpx.Response(503, text="unavailable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        voiceprint = VoicePrintClient("http://voiceprint.example/service?key=test-secret", client=client)
        assert await voiceprint.identify(["speaker-a", "speaker-b"], b"audio") == ("speaker-a", 0.75)
        await voiceprint.register("speaker-a", b"audio")
        with pytest.raises(VoicePrintIntegrationError) as error:
            await voiceprint.cancel("speaker-a")
        assert error.value.code == 10089

    assert all(request.headers["Authorization"] == "Bearer test-secret" for request in requests)
    assert VoicePrintEndpoint.parse("https://voiceprint.example:9443/path?key=secret") == VoicePrintEndpoint(
        "https://voiceprint.example:9443", "Bearer secret"
    )


@pytest.mark.asyncio
@respx.mock
async def test_llm_mock_validates_openai_request_and_thinking_policy() -> None:
    route = respx.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "summary"}}]})
    )
    result = await openai_completion(
        {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "mock-key",
            "model_name": "mock-model",
        },
        "prompt",
        temperature=0.2,
        max_tokens=2000,
        timeout=1,
    )
    assert result == "summary"
    request = route.calls.last.request
    payload = json.loads(request.content)
    assert payload == {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "prompt"}],
        "temperature": 0.2,
        "max_tokens": 2000,
        "enable_thinking": False,
    }
    assert request.headers["Authorization"] == "Bearer mock-key"
