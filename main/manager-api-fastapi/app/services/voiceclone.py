from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.i18n import message_for
from app.core.security import AuthUser, shanghai_now_naive
from app.integrations.voice_clone import VoiceCloneIntegration, VoiceCloneProviderError
from app.repositories.voiceclone import VoiceCloneRepository
from app.schemas.voiceclone import VoiceResourceCreateRequest
from app.services.device import is_blank, redis_delete, redis_get, redis_set

VOICE_ORDER_COLUMNS = {
    "id": "id",
    "name": "name",
    "modelId": "model_id",
    "model_id": "model_id",
    "voiceId": "voice_id",
    "voice_id": "voice_id",
    "userId": "user_id",
    "user_id": "user_id",
    "trainStatus": "train_status",
    "train_status": "train_status",
    "createDate": "create_date",
    "create_date": "create_date",
}


class VoiceCloneService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        redis_client: Redis | None = None,
        http_client: httpx.AsyncClient | None = None,
        provider: VoiceCloneIntegration | None = None,
    ):
        self.session = session
        self.repository = VoiceCloneRepository(session)
        self.redis = redis_client
        self.provider = provider or VoiceCloneIntegration(
            timeout_seconds=get_settings().external_request_timeout_seconds,
            client=http_client,
        )

    async def page(self, query: Mapping[str, Any], *, user_id: int | None = None) -> dict[str, Any]:
        page = int(str(query.get("page") or "1"))
        limit = int(str(query.get("limit") or "10"))
        name_value = query.get("name")
        name = None if name_value is None else str(name_value)
        effective_user = str(user_id) if user_id is not None else self._optional_string(query.get("userId"))
        requested = query.get("orderField")
        requested_fields = [requested] if isinstance(requested, str) else list(requested or [])
        order_fields = [VOICE_ORDER_COLUMNS[field] for field in requested_fields if field in VOICE_ORDER_COLUMNS]
        if not order_fields:
            order_fields = ["create_date"]
        ascending = str(query.get("order") or "").lower() == "asc" if requested_fields else True
        rows = await self.repository.page(
            page=page,
            limit=limit,
            name=name,
            user_id=effective_user,
            order_fields=order_fields,
            ascending=ascending,
        )
        return {
            "total": await self.repository.count(name=name, user_id=effective_user),
            "list": await self._response_list(rows),
        }

    async def get_detail(self, voice_id: str) -> dict[str, Any] | None:
        row = await self.repository.get(voice_id)
        if row is None:
            return None
        return await self._response(row, include_has_voice=False)

    async def get_by_user(self, user_id: int) -> list[dict[str, Any]]:
        del user_id
        # VoiceCloneServiceImpl.getByUserId orders ai_voice_clone by the
        # nonexistent ``created_at`` column (the schema uses ``create_date``).
        # The Java endpoint therefore consistently exposes its generic
        # code-500 envelope before result conversion.
        raise AppError(500)

    async def create_resources(self, request: VoiceResourceCreateRequest, *, actor: AuthUser) -> None:
        model_id = request.model_id or ""
        config = await self._model_config(model_id)
        if config is None:
            raise AppError(10152)
        provider_type = config.get("type")
        if not isinstance(provider_type, str) or not provider_type.strip():
            raise AppError(10153)
        voice_ids = request.voice_ids or []
        for voice_id in voice_ids:
            if is_blank(voice_id):
                continue
            if provider_type == "huoshan_double_stream" and "S_" not in voice_id:
                raise AppError(10160)
            if await self.repository.voice_id_count(model_id=model_id, voice_id=voice_id):
                raise AppError(10159)

        now = shanghai_now_naive()
        prefix = now.strftime("%m%d%H%M")
        values: list[dict[str, Any]] = []
        for index, voice_id in enumerate(voice_ids, start=1):
            values.append(
                {
                    "id": uuid.uuid4().hex,
                    "name": f"{prefix}_{index}",
                    "model_id": model_id,
                    "voice_id": voice_id,
                    "languages": request.languages,
                    "user_id": request.user_id,
                    "voice": None,
                    "train_status": 0,
                    "train_error": None,
                    "creator": actor.id,
                    "create_date": now,
                }
            )
        try:
            await self.repository.insert_many(values)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def delete(self, ids: Sequence[str]) -> None:
        await self.repository.delete_many(ids)
        await self.session.commit()

    async def check_permission(self, voice_id: str | None, user: AuthUser) -> dict[str, Any]:
        row = await self.repository.get(voice_id)
        if row is None:
            raise AppError(10144)
        if int(row.get("user_id") or -1) != user.id:
            raise AppError(10150)
        return row

    async def upload_voice(self, voice_id: str, content: bytes) -> None:
        if await self.repository.get(voice_id) is None:
            raise AppError(10144)
        await self.repository.update_voice(voice_id, content)
        await self.session.commit()

    async def rename(self, voice_id: str, name: str) -> None:
        if await self.repository.get(voice_id) is None:
            raise AppError(10144)
        await self.repository.update_name(voice_id, name)
        await self.session.commit()
        await redis_delete(f"timbre:name:{voice_id}", client=self.redis)

    async def create_audio_id(self, voice_id: str) -> str:
        row = await self.repository.get(voice_id)
        if row is None or row.get("voice") is None:
            raise AppError(10182)
        value = str(uuid.uuid4())
        await redis_set(f"voiceClone:audio:id:{value}", voice_id, client=self.redis)
        return value

    async def consume_audio(self, download_id: str) -> bytes | None:
        key = f"voiceClone:audio:id:{download_id}"
        voice_id = await redis_get(key, self.redis)
        await redis_delete(key, client=self.redis)
        if is_blank(None if voice_id is None else str(voice_id)):
            return None
        row = await self.repository.get(str(voice_id))
        data = None if row is None else row.get("voice")
        if data is None:
            return None
        result = bytes(data)
        return result or None

    async def clone_audio(
        self,
        voice_id: str,
        *,
        accept_language: str | None,
    ) -> None:
        row = await self.repository.get(voice_id)
        if row is None:
            raise AppError(10144)
        raw_voice = row.get("voice")
        if raw_voice is None or len(raw_voice) == 0:
            raise AppError(10151)
        try:
            config = await self._model_config(str(row.get("model_id") or ""))
            if config is None:
                raise AppError(10152)
            provider_type = config.get("type")
            if not isinstance(provider_type, str) or not provider_type.strip():
                raise AppError(10153)
            if provider_type != "huoshan_double_stream":
                return
            appid = config.get("appid")
            access_token = config.get("access_token")
            if (
                not isinstance(appid, str)
                or is_blank(appid)
                or not isinstance(access_token, str)
                or is_blank(access_token)
            ):
                raise AppError(10155)
            speaker_id = await self.provider.train_huoshan(
                appid=appid,
                access_token=access_token,
                voice=bytes(raw_voice),
                speaker_id=str(row.get("voice_id") or ""),
            )
            await self.repository.update_training(
                voice_id,
                train_status=2,
                train_error="",
                speaker_id=speaker_id,
            )
            await self.session.commit()
        except AppError as exc:
            await self._record_training_failure(voice_id, exc.message or message_for(exc.code, accept_language))
            raise
        except VoiceCloneProviderError as exc:
            if exc.code in {500, 10156}:
                await self._record_training_failure(voice_id, exc.message)
                raise AppError(exc.code, exc.message) from exc
            translated = message_for(10154, accept_language, exc.message)
            await self._record_training_failure(voice_id, translated)
            raise AppError(10154, translated) from exc
        except Exception as exc:
            translated = message_for(10154, accept_language, str(exc))
            await self._record_training_failure(voice_id, translated)
            raise AppError(10154, translated) from exc

    async def tts_platforms(self) -> list[dict[str, Any]]:
        return await self.repository.get_tts_platforms()

    async def _record_training_failure(self, voice_id: str, message: str) -> None:
        await self.session.rollback()
        await self.repository.update_training(voice_id, train_status=3, train_error=message)
        await self.session.commit()

    async def _model_config(self, model_id: str) -> dict[str, Any] | None:
        if is_blank(model_id):
            return None
        cached = await redis_get(f"model:data:{model_id}", self.redis)
        cached_mapping = self._mapping(cached)
        if cached_mapping is not None:
            config_value = cached_mapping.get("configJson", cached_mapping.get("config_json"))
            parsed = self._json_mapping(config_value)
            if parsed is not None:
                return parsed
        row = await self.repository.get_model_config(model_id)
        return None if row is None else self._json_mapping(row.get("config_json"))

    async def _model_name(self, model_id: str | None) -> str | None:
        if is_blank(model_id):
            return None
        cache_key = f"model:name:{model_id}"
        cached = await redis_get(cache_key, self.redis)
        if isinstance(cached, str) and cached.strip():
            return cached
        value = await self.repository.get_model_name(model_id or "")
        if value is not None and value.strip():
            await redis_set(cache_key, value, client=self.redis)
        return value

    async def _response_list(self, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        user_ids = [int(row["user_id"]) for row in rows if row.get("user_id") is not None]
        usernames = await self.repository.get_usernames(user_ids)
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(await self._response(row, usernames=usernames, include_has_voice=True))
        return result

    async def _response(
        self,
        row: Mapping[str, Any],
        *,
        usernames: Mapping[int, str] | None = None,
        include_has_voice: bool,
    ) -> dict[str, Any]:
        user_id = None if row.get("user_id") is None else int(row["user_id"])
        if user_id is None:
            username = None
        elif usernames is None:
            username = await self.repository.get_username(user_id)
        else:
            username = usernames.get(user_id)
        return {
            "id": row.get("id"),
            "name": row.get("name"),
            "model_id": row.get("model_id"),
            "model_name": await self._model_name(self._optional_string(row.get("model_id"))),
            "voice_id": row.get("voice_id"),
            "languages": row.get("languages"),
            "user_id": user_id,
            "user_name": username,
            "train_status": row.get("train_status"),
            "train_error": row.get("train_error"),
            "create_date": row.get("create_date"),
            "has_voice": row.get("voice") is not None if include_has_voice else None,
        }

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return {str(key): item for key, item in value.items() if key != "@class"}
        if isinstance(value, list) and len(value) == 2 and isinstance(value[1], dict):
            return {str(key): item for key, item in value[1].items()}
        return None

    @staticmethod
    def _json_mapping(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return {str(key): item for key, item in value.items()}
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return None
            return {str(key): item for key, item in parsed.items()} if isinstance(parsed, dict) else None
        return None

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        return None if value is None else str(value)
