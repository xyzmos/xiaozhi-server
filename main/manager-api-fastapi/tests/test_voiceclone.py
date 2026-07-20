from __future__ import annotations

import base64
import json
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import AuthUser
from app.integrations.voice_clone import VoiceCloneIntegration
from app.routers.voiceclone import voiceclone_router
from app.schemas.voiceclone import VoiceResourceCreateRequest
from app.services.voiceclone import VoiceCloneService
from tests.domain_support import FakeRedis, sqlite_session

VOICE_SCHEMA = [
    """
    CREATE TABLE ai_voice_clone (
      id VARCHAR(32) PRIMARY KEY, name VARCHAR(64), model_id VARCHAR(32), voice_id VARCHAR(32),
      languages VARCHAR(50), user_id BIGINT, voice BLOB, train_status INTEGER, train_error VARCHAR(255),
      creator BIGINT, create_date DATETIME
    )
    """,
    """
    CREATE TABLE ai_model_config (
      id VARCHAR(32) PRIMARY KEY, model_type VARCHAR(20), model_name VARCHAR(50), config_json JSON
    )
    """,
    "CREATE TABLE sys_user (id BIGINT PRIMARY KEY, username VARCHAR(50))",
]


def user(user_id: int = 8, *, super_admin: int = 0) -> AuthUser:
    return AuthUser(
        id=user_id,
        username="voice-user",
        super_admin=super_admin,
        status=1,
        token="test-token",  # noqa: S106 - isolated authentication fixture
        row={"id": user_id},
    )


def test_voiceclone_router_closes_twelve_paths_with_static_paths_first() -> None:
    routes = [route for route in voiceclone_router.routes if hasattr(route, "methods")]
    pairs = {(next(iter(route.methods)), route.path) for route in routes}
    assert pairs == {
        ("GET", "/voiceResource/ttsPlatforms"),
        ("GET", "/voiceResource/user/{user_id}"),
        ("GET", "/voiceResource"),
        ("GET", "/voiceResource/{voice_id}"),
        ("POST", "/voiceResource"),
        ("DELETE", "/voiceResource/{voice_id}"),
        ("GET", "/voiceClone"),
        ("POST", "/voiceClone/upload"),
        ("POST", "/voiceClone/updateName"),
        ("POST", "/voiceClone/audio/{voice_id}"),
        ("GET", "/voiceClone/play/{download_id}"),
        ("POST", "/voiceClone/cloneAudio"),
    }
    assert len(routes) == len(pairs)
    paths = [route.path for route in routes]
    assert paths.index("/voiceResource/ttsPlatforms") < paths.index("/voiceResource/{voice_id}")
    assert paths.index("/voiceResource/user/{user_id}") < paths.index("/voiceResource/{voice_id}")


@pytest.mark.asyncio
async def test_voice_resource_create_page_upload_and_one_time_audio() -> None:
    fake = cast(Redis, FakeRedis())
    async with sqlite_session(VOICE_SCHEMA) as session:
        await session.execute(text("INSERT INTO sys_user VALUES (8, 'voice-user')"))
        await session.execute(
            text(
                "INSERT INTO ai_model_config (id,model_type,model_name,config_json) "
                "VALUES ('tts-1','TTS','火山双向流',:config)"
            ),
            {"config": json.dumps({"type": "huoshan_double_stream", "appid": "app", "access_token": "token"})},
        )
        await session.commit()
        service = VoiceCloneService(session, redis_client=fake)
        await service.create_resources(
            VoiceResourceCreateRequest(
                model_id="tts-1",
                voice_ids=["S_voice_one"],
                user_id=8,
                languages="zh-CN",
            ),
            actor=user(super_admin=1),
        )
        page = await service.page({"page": "1", "limit": "10"}, user_id=8)
        assert page["total"] == 1
        item = page["list"][0]
        assert item["model_name"] == "火山双向流"
        assert item["user_name"] == "voice-user"
        assert item["has_voice"] is False
        voice_id = str(item["id"])
        await service.check_permission(voice_id, user())
        await service.upload_voice(voice_id, b"RIFF-test-wave")
        download_id = await service.create_audio_id(voice_id)
        assert await service.consume_audio(download_id) == b"RIFF-test-wave"
    assert await service.consume_audio(download_id) is None


@pytest.mark.asyncio
async def test_voice_resources_by_user_keeps_java_created_at_query_failure() -> None:
    async with sqlite_session(VOICE_SCHEMA) as session:
        with pytest.raises(AppError) as caught:
            await VoiceCloneService(session).get_by_user(9223372036854775806)
    assert caught.value.code == 500


@pytest.mark.asyncio
async def test_huoshan_clone_request_and_success_state_are_persisted() -> None:
    fake = cast(Redis, FakeRedis())
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        assert payload["appid"] == "app-id"
        assert base64.b64decode(payload["audios"][0]["audio_bytes"]) == b"voice-bytes"
        assert payload["audios"][0]["audio_format"] == "wav"
        assert payload["source"] == 2
        assert payload["language"] == 0
        assert payload["model_type"] == 1
        assert payload["speaker_id"] == "S_original"
        return httpx.Response(200, json={"BaseResp": {"StatusCode": 0}, "speaker_id": "S_trained"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = VoiceCloneIntegration(timeout_seconds=1, client=client, endpoint="https://mock.local/train")
        async with sqlite_session(VOICE_SCHEMA) as session:
            await _seed_clone(session)
            service = VoiceCloneService(session, redis_client=fake, provider=provider)
            await service.clone_audio("clone-1", accept_language="zh-CN")
            row = (
                await session.execute(
                    text("SELECT voice_id,train_status,train_error FROM ai_voice_clone WHERE id='clone-1'")
                )
            ).mappings().one()
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer;access-token"
    assert requests[0].headers["Resource-Id"] == "seed-icl-1.0"
    assert row == {"voice_id": "S_trained", "train_status": 2, "train_error": ""}


@pytest.mark.asyncio
async def test_huoshan_timeout_maps_to_training_error_without_retry() -> None:
    fake = cast(Redis, FakeRedis())
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("provider timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = VoiceCloneIntegration(timeout_seconds=0.01, client=client, endpoint="https://mock.local/train")
        async with sqlite_session(VOICE_SCHEMA) as session:
            await _seed_clone(session)
            service = VoiceCloneService(session, redis_client=fake, provider=provider)
            with pytest.raises(AppError) as raised:
                await service.clone_audio("clone-1", accept_language="en-US")
            row = (
                await session.execute(
                    text("SELECT train_status,train_error FROM ai_voice_clone WHERE id='clone-1'")
                )
            ).mappings().one()
    assert attempts == 1
    assert raised.value.code == 10154
    assert row["train_status"] == 3
    assert "provider timeout" in row["train_error"]


@pytest.mark.asyncio
async def test_voice_play_route_consumes_link_and_preserves_audio_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = cast(Redis, FakeRedis())
    monkeypatch.setattr("app.services.device.get_redis", lambda: fake)
    await cast(Any, fake).set("voiceClone:audio:id:play-once", b'"clone-1"', ex=86_400)
    async with sqlite_session(VOICE_SCHEMA) as session:
        await session.execute(
            text(
                "INSERT INTO ai_voice_clone "
                "(id,name,model_id,voice_id,user_id,voice,train_status,creator,create_date) "
                "VALUES ('clone-1','voice','tts','S_voice',8,:voice,0,8,CURRENT_TIMESTAMP)"
            ),
            {"voice": b"RIFF-audio"},
        )
        await session.commit()
        app = FastAPI()
        app.include_router(voiceclone_router)

        async def override_db() -> Any:
            yield session

        app.dependency_overrides[get_db] = override_db
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = await client.get("/voiceClone/play/play-once")
            second = await client.get("/voiceClone/play/play-once")
    assert first.status_code == 200
    assert first.content == b"RIFF-audio"
    assert first.headers["content-type"] == "audio/wav"
    assert first.headers["content-length"] == str(len(first.content))
    assert first.headers["content-disposition"] == "inline; filename=voice.wav"
    assert second.status_code == 404


async def _seed_clone(session: Any) -> None:
    await session.execute(text("INSERT INTO sys_user VALUES (8, 'voice-user')"))
    await session.execute(
        text(
            "INSERT INTO ai_model_config (id,model_type,model_name,config_json) "
            "VALUES ('tts-1','TTS','火山双向流',:config)"
        ),
        {
            "config": json.dumps(
                {"type": "huoshan_double_stream", "appid": "app-id", "access_token": "access-token"}
            )
        },
    )
    await session.execute(
        text(
            "INSERT INTO ai_voice_clone "
            "(id,name,model_id,voice_id,languages,user_id,voice,train_status,creator,create_date) "
            "VALUES ('clone-1','clone','tts-1','S_original','zh-CN',8,:voice,0,8,CURRENT_TIMESTAMP)"
        ),
        {"voice": b"voice-bytes"},
    )
    await session.commit()
