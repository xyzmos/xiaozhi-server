from __future__ import annotations

import json
from datetime import datetime

import pytest
from sqlalchemy import text
from starlette.requests import Request
from starlette.routing import Match

from app.core.errors import AppError
from app.core.security import AuthUser
from app.main import app
from app.repositories.correctword import CorrectWordRepository
from app.repositories.model import ModelRepository
from app.repositories.timbre import TimbreRepository
from app.routers.correctword import _java_urlencode, download_file
from app.schemas.correctword import CorrectWordFileBody
from app.schemas.model import ModelConfigBody, ModelProviderBody
from app.schemas.timbre import TimbreBody
from app.services.correctword import CorrectWordService, file_vo
from app.services.model import ModelProviderService, ModelService, _mask_middle
from app.services.timbre import TimbreService, _details, _validation_message
from tests.domain_support import FakeRedis, sqlite_session

USER = AuthUser(id=2147483648, username="tester", super_admin=1, status=1, token=str(2147483648), row={})

MODEL_SCHEMA = [
    "CREATE TABLE ai_model_config (id TEXT PRIMARY KEY, model_type TEXT, model_code TEXT, model_name TEXT, "
    "is_default INTEGER DEFAULT 0, is_enabled INTEGER DEFAULT 0, config_json TEXT, doc_link TEXT, remark TEXT, "
    "sort INTEGER DEFAULT 0)",
    "CREATE TABLE ai_model_provider (id TEXT PRIMARY KEY, model_type TEXT, provider_code TEXT, name TEXT, "
    "fields TEXT, sort INTEGER, creator INTEGER, create_date DATETIME, updater INTEGER, update_date DATETIME)",
]

TIMBRE_SCHEMA = [
    "CREATE TABLE ai_tts_voice (id TEXT PRIMARY KEY, languages TEXT, name TEXT, remark TEXT, "
    "reference_audio TEXT, reference_text TEXT, sort INTEGER, tts_model_id TEXT, tts_voice TEXT, "
    "voice_demo TEXT, creator INTEGER, create_date DATETIME, updater INTEGER, update_date DATETIME)",
]

CORRECTWORD_SCHEMA = [
    "CREATE TABLE ai_agent_correct_word_file (id TEXT PRIMARY KEY, file_name TEXT, word_count INTEGER, "
    "content TEXT, creator INTEGER, created_at DATETIME, updater INTEGER, updated_at DATETIME)",
    "CREATE TABLE ai_agent_correct_word_item (id TEXT PRIMARY KEY, file_id TEXT, source_word TEXT, target_word TEXT)",
    "CREATE TABLE ai_agent_correct_word_mapping (id TEXT, agent_id TEXT, file_id TEXT)",
]


def test_model_enable_specific_route_precedes_generic_model_edit() -> None:
    scope = {"type": "http", "method": "PUT", "path": "/xiaozhi/models/enable/model/0"}
    endpoint_name = None
    for route in app.routes:
        match, _ = route.matches(scope)
        if match is Match.FULL:
            endpoint_name = route.endpoint.__name__
            break
    assert endpoint_name == "model_enable"


@pytest.mark.asyncio
async def test_model_edit_preserves_not_null_columns_but_returns_request_nulls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    monkeypatch.setattr("app.services.model.get_redis", lambda: redis)
    async with sqlite_session(MODEL_SCHEMA) as session:
        await session.execute(
            text(
                "INSERT INTO ai_model_provider VALUES "
                "('provider', 'LLM', 'openai', 'OpenAI', '{}', 1, 1, NULL, 1, NULL)"
            )
        )
        await session.execute(
            text(
                "INSERT INTO ai_model_config VALUES "
                "('model', 'LLM', 'openai', 'Original', 0, 1, "
                "'{\"api_key\":\"secret-value\",\"model\":\"gpt\"}', 'doc', 'remark', 9)"
            )
        )
        await session.commit()

        result = await ModelService(ModelRepository(session)).edit(
            "LLM",
            "openai",
            "model",
            ModelConfigBody(config_json={"api_key": "secr****alue", "model": "new"}),
        )
        stored = (
            await session.execute(
                text("SELECT model_name,is_enabled,remark,sort,config_json FROM ai_model_config WHERE id='model'")
            )
        ).mappings().one()

        assert result["modelName"] is None and result["isEnabled"] is None and result["sort"] is None
        assert stored["model_name"] == "Original" and stored["is_enabled"] == 1
        assert stored["remark"] == "remark" and stored["sort"] == 9
        assert json.loads(stored["config_json"]) == {"api_key": "secret-value", "model": "new"}
        assert _mask_middle("   ") == "   "
        assert "model:data:model" not in redis.values


@pytest.mark.asyncio
async def test_model_insert_defaults_and_provider_generated_id_response_match_java() -> None:
    async with sqlite_session(MODEL_SCHEMA) as session:
        await session.execute(
            text(
                "INSERT INTO ai_model_provider VALUES "
                "('provider', 'ASR', 'mock', 'Mock', '{}', 1, 1, NULL, 1, NULL)"
            )
        )
        await session.commit()
        model = await ModelService(ModelRepository(session)).add(
            "ASR", "mock", ModelConfigBody(model_code="mock", model_name="ASR")
        )
        stored_defaults = (
            await session.execute(text("SELECT is_enabled,sort FROM ai_model_config WHERE id=:id"), {"id": model["id"]})
        ).one()
        # The assertion query starts its own read transaction; close it before
        # exercising the next independently scoped service call.
        await session.commit()
        provider = await ModelProviderService(ModelRepository(session)).add(
            ModelProviderBody(
                model_type="TTS", provider_code="new-provider", name="New", fields="not-json", sort=2
            ),
            USER,
        )

        assert model["isEnabled"] is None and model["sort"] is None
        assert tuple(stored_defaults) == (0, 0)
        assert provider["id"] is None
        provider_count = await session.scalar(
            text("SELECT COUNT(*) FROM ai_model_provider WHERE provider_code='new-provider'")
        )
        assert provider_count == 1


def test_timbre_validation_is_localized_code_500_and_long_sort_is_string() -> None:
    with pytest.raises(AppError) as caught:
        TimbreService._validate(TimbreBody(), "en-US")
    assert caught.value.code == 500
    assert caught.value.message == _validation_message("timbre.languages.require", "en-US")
    assert _details({"sort": 2147483648})["sort"] == "2147483648"
    assert _details({"sort": None})["sort"] == "0"


@pytest.mark.asyncio
async def test_timbre_update_preserves_nullable_columns_and_clears_java_cache_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    await redis.set("timbre:details:voice", b"cached")
    monkeypatch.setattr("app.services.timbre.get_redis", lambda: redis)
    async with sqlite_session(TIMBRE_SCHEMA) as session:
        await session.execute(
            text(
                "INSERT INTO ai_tts_voice VALUES "
                "('voice','zh','Old','remark','ref.wav','hello',7,'tts','old-code','demo.wav',1,NULL,NULL,NULL)"
            )
        )
        await session.commit()
        await TimbreService(TimbreRepository(session)).update(
            "voice",
            TimbreBody(languages="en", name="New", tts_model_id="tts", tts_voice="new-code", sort=None),
            USER,
            "en-US",
        )
        row = (
            await session.execute(
                text(
                    "SELECT languages,name,remark,reference_audio,reference_text,sort,tts_voice,voice_demo "
                    "FROM ai_tts_voice WHERE id='voice'"
                )
            )
        ).one()
        assert tuple(row) == ("en", "New", "remark", "ref.wav", "hello", 0, "new-code", "demo.wav")
        assert await redis.get("timbre:details:voice") is None


def test_correctword_validation_size_and_java_line_semantics() -> None:
    with pytest.raises(AppError) as missing:
        CorrectWordService.validate(CorrectWordFileBody(), check_size=True)
    assert (missing.value.code, missing.value.message) == (10034, "文件名不能为空")

    oversized = CorrectWordFileBody(file_name="words.txt", content=["a|b"], file_size=1024 * 1024 + 1)
    with pytest.raises(AppError) as too_large:
        CorrectWordService.validate(oversized, check_size=True)
    assert too_large.value.code == 10204
    CorrectWordService.validate(oversized, check_size=False)
    assert file_vo({"content": ""})["content"] == [""]
    assert file_vo({"content": "a|b\n"})["content"] == ["a|b"]


@pytest.mark.asyncio
async def test_correctword_empty_download_and_java_content_disposition() -> None:
    async with sqlite_session(CORRECTWORD_SCHEMA) as session:
        await session.execute(
            text(
                "INSERT INTO ai_agent_correct_word_file VALUES "
                "('file','中~* a.txt',0,'',2147483648,:now,NULL,NULL)"
            ),
            {"now": datetime(2026, 7, 20, 10, 0, 0)},
        )
        await session.commit()
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        request.state.user = USER
        response = await download_file("file", request, session)

        assert response.status_code == 200 and response.body == b""
        assert response.media_type == "application/octet-stream"
        assert response.headers["content-length"] == "0"
        assert response.headers["content-disposition"] == (
            "attachment; filename=\"_~* a.txt\"; filename*=UTF-8''%E4%B8%AD%7E*%20a.txt"
        )
        assert _java_urlencode("中~* a.txt") == "%E4%B8%AD%7E*%20a.txt"


@pytest.mark.asyncio
async def test_correctword_update_accepts_large_declared_size() -> None:
    async with sqlite_session(CORRECTWORD_SCHEMA) as session:
        await session.execute(
            text(
                "INSERT INTO ai_agent_correct_word_file VALUES "
                "('file','old.txt',1,'a|b',2147483648,NULL,NULL,NULL)"
            )
        )
        await session.execute(text("INSERT INTO ai_agent_correct_word_item VALUES ('item','file','a','b')"))
        await session.commit()
        await CorrectWordService(CorrectWordRepository(session)).update(
            "file",
            CorrectWordFileBody(
                file_name="new.txt", content=["a|b", "invalid", " c | d "], file_size=2 * 1024 * 1024
            ),
            USER,
        )
        row = (
            await session.execute(
                text("SELECT file_name,word_count,content FROM ai_agent_correct_word_file WHERE id='file'")
            )
        ).one()
        assert tuple(row) == ("new.txt", 2, "a|b\ninvalid\n c | d ")
        assert await session.scalar(text("SELECT COUNT(*) FROM ai_agent_correct_word_item WHERE file_id='file'")) == 2
