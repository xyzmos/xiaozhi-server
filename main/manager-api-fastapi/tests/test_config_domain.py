from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.redis import JavaRedisCodec
from app.repositories.config import ConfigRepository
from app.routers.config import config_router
from app.services.config import ConfigService
from tests.domain_support import FakeRedis, sqlite_session

CONFIG_SCHEMA = [
    "CREATE TABLE sys_params ("
    "id INTEGER PRIMARY KEY, param_code TEXT UNIQUE, param_value TEXT, value_type TEXT, param_type INTEGER)",
    "CREATE TABLE ai_agent_template ("
    "id TEXT PRIMARY KEY, agent_code TEXT, agent_name TEXT, asr_model_id TEXT, vad_model_id TEXT, "
    "llm_model_id TEXT, slm_model_id TEXT, vllm_model_id TEXT, tts_model_id TEXT, tts_voice_id TEXT, "
    "tts_language TEXT, tts_volume INTEGER, tts_rate INTEGER, tts_pitch INTEGER, mem_model_id TEXT, "
    "intent_model_id TEXT, chat_history_conf INTEGER, system_prompt TEXT, summary_memory TEXT, "
    "lang_code TEXT, language TEXT, sort INTEGER)",
    "CREATE TABLE ai_device ("
    "id TEXT PRIMARY KEY, user_id INTEGER, mac_address TEXT UNIQUE, board TEXT, agent_id TEXT, "
    "app_version TEXT, auto_update INTEGER)",
    "CREATE TABLE ai_agent ("
    "id TEXT PRIMARY KEY, user_id INTEGER, agent_code TEXT, agent_name TEXT, asr_model_id TEXT, "
    "vad_model_id TEXT, llm_model_id TEXT, slm_model_id TEXT, vllm_model_id TEXT, tts_model_id TEXT, "
    "tts_voice_id TEXT, tts_language TEXT, tts_volume INTEGER, tts_rate INTEGER, tts_pitch INTEGER, "
    "mem_model_id TEXT, intent_model_id TEXT, chat_history_conf INTEGER, system_prompt TEXT, "
    "summary_memory TEXT, lang_code TEXT, language TEXT)",
    "CREATE TABLE ai_model_config ("
    "id TEXT PRIMARY KEY, model_type TEXT, model_code TEXT, model_name TEXT, is_default INTEGER, "
    "is_enabled INTEGER, config_json TEXT, doc_link TEXT, remark TEXT, sort INTEGER, creator INTEGER, "
    "create_date DATETIME, updater INTEGER, update_date DATETIME)",
    "CREATE TABLE ai_tts_voice ("
    "id TEXT PRIMARY KEY, languages TEXT, name TEXT, remark TEXT, reference_audio TEXT, "
    "reference_text TEXT, sort INTEGER, tts_model_id TEXT, tts_voice TEXT, voice_demo TEXT)",
    "CREATE TABLE ai_voice_clone ("
    "id TEXT PRIMARY KEY, name TEXT, model_id TEXT, voice_id TEXT, languages TEXT, user_id INTEGER, "
    "train_status INTEGER, train_error TEXT)",
    "CREATE TABLE ai_agent_plugin_mapping ("
    "id TEXT PRIMARY KEY, agent_id TEXT, plugin_id TEXT, param_info TEXT)",
    "CREATE TABLE ai_model_provider (id TEXT PRIMARY KEY, provider_code TEXT)",
    "CREATE TABLE ai_rag_dataset ("
    "id TEXT PRIMARY KEY, dataset_id TEXT, rag_model_id TEXT, name TEXT, description TEXT, status INTEGER)",
    "CREATE TABLE ai_agent_context_provider (agent_id TEXT PRIMARY KEY, context_providers TEXT)",
    "CREATE TABLE ai_agent_voice_print ("
    "id TEXT PRIMARY KEY, agent_id TEXT, source_name TEXT, introduce TEXT, create_date DATETIME)",
    "CREATE TABLE ai_agent_correct_word_mapping (agent_id TEXT, file_id TEXT)",
    "CREATE TABLE ai_agent_correct_word_item (file_id TEXT, source_word TEXT, target_word TEXT)",
]


async def _seed_config(session: AsyncSession) -> None:
    execute = session.execute
    await execute(
        text(
            "INSERT INTO sys_params VALUES "
            "(1, 'server.port', '8000', 'number', 1),"
            "(2, 'features.enabled', 'true', 'boolean', 1),"
            "(3, 'allowed.languages', 'zh; en ;', 'array', 1),"
            "(4, 'device_max_output_size', '2048', 'string', 1),"
            "(5, 'server.mcp_endpoint', 'https://mcp.example.test/mcp/?key=0123456789abcdef', 'string', 1),"
            "(6, 'server.voice_print', 'https://voice.example.test/identify', 'string', 1),"
            "(7, 'server.voiceprint_similarity_threshold', '0.73', 'number', 1)"
        )
    )
    await execute(
        text(
            "INSERT INTO ai_agent_template "
            "(id, agent_code, agent_name, asr_model_id, vad_model_id, sort) "
            "VALUES ('template-1', 'default', 'Default', 'asr-1', 'vad-1', 1)"
        )
    )
    models = [
        ("vad-1", "VAD", "vad", {"type": "silero"}),
        ("asr-1", "ASR", "asr", {"type": "funasr"}),
        ("llm-1", "LLM", "llm", {"type": "openai", "model": "mock"}),
        ("tts-1", "TTS", "tts", {"type": "huoshan_double_stream"}),
        ("mem-1", "Memory", "mem", {"type": "mem_local_short", "llm": "llm-1"}),
        ("intent-1", "Intent", "intent", {"type": "intent_llm", "llm": "llm-1", "functions": "a;b"}),
        ("rag-1", "RAG", "ragflow", {"base_url": "https://rag.test", "api_key": "mock-key"}),
    ]
    for index, (model_id, model_type, model_code, configuration) in enumerate(models, start=1):
        await execute(
            text(
                "INSERT INTO ai_model_config "
                "(id, model_type, model_code, model_name, is_default, is_enabled, config_json, sort) "
                "VALUES (:id, :type, :code, :name, 0, 1, :config, :sort)"
            ),
            {
                "id": model_id,
                "type": model_type,
                "code": model_code,
                "name": model_code,
                "config": json.dumps(configuration),
                "sort": index,
            },
        )


@pytest.mark.asyncio
async def test_server_base_types_modules_and_redis_cache() -> None:
    redis = FakeRedis()
    async with sqlite_session(CONFIG_SCHEMA) as session:
        await _seed_config(session)
        await session.commit()
        service = ConfigService(ConfigRepository(session), redis=redis)  # type: ignore[arg-type]
        result = await service.get_config(use_cache=False)

        assert result["server"]["port"] == 8000
        assert result["features"]["enabled"] is True
        assert result["allowed"]["languages"] == ["zh", "en"]
        assert ConfigService._typed_param("2147483647", "number") == 2147483647
        assert ConfigService._typed_param("2147483648", "number") == 2147483648.0
        assert isinstance(ConfigService._typed_param("2147483648", "number"), float)
        assert result["VAD"]["vad-1"] == {"type": "silero"}
        assert result["ASR"]["asr-1"] == {"type": "funasr"}
        assert result["selected_module"] == {"VAD": "vad-1", "ASR": "asr-1"}
        assert JavaRedisCodec.decode(await redis.get("server:config")) == result
        server_wire = json.loads((await redis.get("server:config")).decode())
        assert server_wire["@class"] == "java.util.HashMap"
        assert server_wire["server"]["@class"] == "java.util.HashMap"
        assert 0 < await redis.ttl("server:config") <= 86400

        await session.execute(text("UPDATE sys_params SET param_value = '9000' WHERE param_code = 'server.port'"))
        await session.commit()
        assert (await service.get_config(use_cache=True))["server"]["port"] == 8000


@pytest.mark.asyncio
async def test_agent_config_aggregation_selected_models_mcp_voiceprint_and_correct_words() -> None:
    redis = FakeRedis()
    async with sqlite_session(CONFIG_SCHEMA) as session:
        await _seed_config(session)
        await session.execute(
            text(
                "INSERT INTO ai_device VALUES "
                "('device-1', 10, 'AA:BB:CC:DD:EE:FF', 'esp32s3', 'agent-1', '1.2.3', 1)"
            )
        )
        await session.execute(
            text(
                "INSERT INTO ai_agent "
                "(id, user_id, agent_code, agent_name, asr_model_id, vad_model_id, llm_model_id, "
                "tts_model_id, tts_voice_id, tts_volume, tts_rate, tts_pitch, mem_model_id, intent_model_id, "
                "system_prompt, summary_memory) VALUES "
                "('agent-1', 10, 'a1', '小明', 'asr-1', 'vad-1', 'llm-1', 'tts-1', 'voice-1', "
                "80, 2, -1, 'mem-1', 'intent-1', '你是{{assistant_name}}', 'memory')"
            )
        )
        await session.execute(
            text(
                "INSERT INTO ai_tts_voice "
                "(id, languages, name, reference_audio, reference_text, sort, tts_model_id, tts_voice) "
                "VALUES ('voice-1', '普通话、English', 'Voice', 'ref.wav', '你好', 2147483648, "
                "'tts-1', 'S_demo')"
            )
        )
        await session.execute(
            text("UPDATE ai_model_config SET creator = 2147483648, updater = 2147483649 WHERE id = 'tts-1'")
        )
        await session.execute(text("INSERT INTO ai_model_provider VALUES ('weather-plugin', 'weather')"))
        await session.execute(
            text(
                "INSERT INTO ai_agent_plugin_mapping VALUES "
                "('map-1', 'agent-1', 'weather-plugin', '{\"city\":\"shanghai\"}'),"
                "('map-2', 'agent-1', 'dataset-row', NULL)"
            )
        )
        await session.execute(
            text(
                "INSERT INTO ai_rag_dataset VALUES "
                "('dataset-row', 'dataset-external', 'rag-1', 'FAQ', 'product questions', 1)"
            )
        )
        await session.execute(
            text("INSERT INTO ai_agent_context_provider VALUES ('agent-1', '[{\"type\":\"weather\"}]')")
        )
        await session.execute(
            text(
                "INSERT INTO ai_agent_voice_print VALUES "
                "('vp-1', 'agent-1', 'Alice', 'owner', '2026-01-02 03:04:05')"
            )
        )
        await session.execute(text("INSERT INTO ai_agent_correct_word_mapping VALUES ('agent-1', 'file-1')"))
        await session.execute(
            text(
                "INSERT INTO ai_agent_correct_word_item VALUES "
                "('file-1', '晓智', '小智'), ('file-1', NULL, '空值')"
            )
        )
        await session.commit()

        service = ConfigService(ConfigRepository(session), redis=redis)  # type: ignore[arg-type]
        result = await service.get_agent_models("AA:BB:CC:DD:EE:FF", {"VAD": "vad-1"})

        assert result["device_max_output_size"] == "2048"
        assert result["chat_history_conf"] == 2
        assert "VAD" not in result and result["selected_module"]["ASR"] == "asr-1"
        assert result["prompt"] == "你是小明"
        assert result["TTS"]["tts-1"] == {
            "type": "huoshan_double_stream",
            "private_voice": "S_demo",
            "ref_audio": "ref.wav",
            "ref_text": "你好",
            "language": "普通话",
            "ttsVolume": 80,
            "ttsRate": 2,
            "ttsPitch": -1,
            "resource_id": "seed-icl-1.0",
        }
        assert result["Intent"]["intent-1"]["functions"] == ["a", "b"]
        assert result["plugins"]["weather"] == '{"city":"shanghai"}'
        rag_plugin = json.loads(result["plugins"]["search_from_ragflow"])
        assert rag_plugin["dataset_ids"] == ["dataset-external"]
        # This preserves URI.getSchemeSpecificPart() in Java, including its nested /mcp segment.
        assert result["mcp_endpoint"].startswith("wss://mcp.example.test/call/mcp/?token=")
        assert result["context_providers"] == [{"type": "weather"}]
        assert result["voiceprint"] == {
            "url": "https://voice.example.test/identify",
            "speakers": ["vp-1,Alice,owner"],
            "similarity_threshold": 0.73,
        }
        assert set(await service.get_correct_words("AA:BB:CC:DD:EE:FF")) == {"晓智|小智", "null|空值"}
        model_wire = json.loads((await redis.get("model:data:tts-1")).decode())
        assert model_wire["@class"] == "xiaozhi.modules.model.entity.ModelConfigEntity"
        assert model_wire["configJson"]["@class"] == "cn.hutool.json.JSONObject"
        assert model_wire["creator"] == 2147483648
        assert model_wire["updater"] == 2147483649
        timbre_wire = json.loads((await redis.get("timbre:details:voice-1")).decode())
        assert timbre_wire["@class"] == "xiaozhi.modules.timbre.vo.TimbreDetailsVO"
        assert timbre_wire["sort"] == 2147483648


@pytest.mark.asyncio
async def test_temporary_admin_config_is_one_shot_and_activation_code_error_is_preserved() -> None:
    redis = FakeRedis()
    async with sqlite_session(CONFIG_SCHEMA) as session:
        await _seed_config(session)
        await session.commit()
        service = ConfigService(ConfigRepository(session), redis=redis)  # type: ignore[arg-type]

        await redis.set("tmp_register_mac:temporary", JavaRedisCodec.encode("true"), ex=300)
        temporary = await service.get_agent_models("temporary", {})
        assert temporary["selected_module"] == {"VAD": "vad-1", "ASR": "asr-1"}
        assert await redis.get("tmp_register_mac:temporary") is None

        await redis.set(
            "ota:activation:data:aa_bb_cc_dd_ee_11",
            JavaRedisCodec.encode({"activation_code": "654321"}),
            ex=300,
        )
        with pytest.raises(AppError) as captured:
            await service.get_agent_models("AA:BB:CC:DD:EE:11", {})
        assert captured.value.code == 10042
        assert captured.value.params == ("654321",)


@pytest.mark.asyncio
async def test_invalid_model_config_fails_like_java_jackson_type_handler() -> None:
    redis = FakeRedis()
    async with sqlite_session(CONFIG_SCHEMA) as session:
        await _seed_config(session)
        await session.execute(text("UPDATE ai_model_config SET config_json = '{' WHERE id = 'vad-1'"))
        await session.commit()
        service = ConfigService(ConfigRepository(session), redis=redis)  # type: ignore[arg-type]
        with pytest.raises(json.JSONDecodeError):
            await service.get_config(use_cache=False)


def test_config_router_exposes_all_config_controller_routes() -> None:
    routes = {(method, route.path) for route in config_router.routes for method in route.methods}
    assert routes == {
        ("POST", "/config/server-base"),
        ("POST", "/config/agent-models"),
        ("POST", "/config/correct-words"),
    }
