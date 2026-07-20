from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.config import get_settings
from app.core.i18n import _load_properties, message_for, resolve_language
from app.core.ids import snowflake
from app.core.redis import JavaRedisCodec, get_redis
from app.core.security import AuthUser, shanghai_now_naive
from app.repositories.timbre import TimbreRepository
from app.schemas.timbre import TimbreBody


def _details(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "languages": row.get("languages"),
        "name": row.get("name"),
        "remark": row.get("remark"),
        "referenceAudio": row.get("reference_audio"),
        "referenceText": row.get("reference_text"),
        # TimbreDetailsVO.sort is primitive long, whose Java serializer always
        # emits a string and whose null conversion default is zero.
        "sort": str(row.get("sort") if row.get("sort") is not None else 0),
        "ttsModelId": row.get("tts_model_id"),
        "ttsVoice": row.get("tts_voice"),
        "voiceDemo": row.get("voice_demo"),
    }


class TimbreService:
    def __init__(self, repository: TimbreRepository):
        self.repository = repository

    @staticmethod
    def _validate(body: TimbreBody, language: str | None) -> None:
        from app.core.errors import AppError

        for value, message in (
            (body.languages, "timbre.languages.require"),
            (body.name, "timbre.name.require"),
            (body.tts_model_id, "timbre.ttsModelId.require"),
            (body.tts_voice, "timbre.ttsVoice.require"),
        ):
            if value is None or not value.strip():
                # TimbreController invokes ValidatorUtils directly.  That
                # utility wraps validation text in RenException(String), whose
                # response code is 500 rather than the global @Valid code 10034.
                raise AppError(500, _validation_message(message, language))
        if body.sort is not None and body.sort < 0:
            raise AppError(500, _validation_message("sort.number", language))

    async def page(
        self,
        tts_model_id: str | None,
        name: str | None,
        page: str | None,
        limit: str | None,
        language: str | None,
    ) -> dict[str, Any]:
        if tts_model_id is None or not tts_model_id.strip():
            from app.core.errors import AppError

            raise AppError(500, _validation_message("timbre.ttsModelId.require", language))
        current, size = max(int(page or "1"), 1), int(limit or "10")
        rows, total = await self.repository.page(
            tts_model_id=tts_model_id, name=name, offset=(current - 1) * size, limit=size
        )
        return {"total": total, "list": [_details(row) for row in rows]}

    async def save(self, body: TimbreBody, user: AuthUser, language: str | None) -> None:
        self._validate(body, language)
        values = self._values(body, user, str(snowflake.next_id()))
        async with self.repository.session.begin():
            await self.repository.insert(values)

    async def update(
        self, timbre_id: str, body: TimbreBody, user: AuthUser, language: str | None
    ) -> None:
        self._validate(body, language)
        values = self._values(body, user, timbre_id)
        async with self.repository.session.begin():
            await self.repository.update(values)
        await get_redis().delete(f"timbre:details:{timbre_id}")

    async def delete(self, ids: list[str]) -> None:
        async with self.repository.session.begin():
            await self.repository.delete(ids)

    async def voices(self, model_id: str, voice_name: str | None, user: AuthUser, language: str | None) -> Any:
        normal, clones = await self.repository.voices(model_id, voice_name, user.id)
        values = [
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "voiceDemo": row.get("voice_demo"),
                "languages": row.get("languages"),
                "isClone": False,
            }
            for row in normal
        ]
        prefix = message_for(10158, language)
        redis = get_redis()
        for row in clones:
            name = prefix + str(row.get("name") or "")
            voice = {
                "id": row.get("id"),
                "name": name,
                "voiceDemo": row.get("voice_demo"),
                "languages": row.get("languages"),
                "isClone": True,
            }
            await redis.set(f"timbre:name:{row['id']}", JavaRedisCodec.encode(name))
            values.insert(0, voice)
        return values or None

    @staticmethod
    def _values(body: TimbreBody, user: AuthUser, timbre_id: str) -> dict[str, Any]:
        assert body.languages is not None
        assert body.name is not None
        assert body.tts_model_id is not None
        assert body.tts_voice is not None
        return {
            "id": timbre_id,
            "languages": body.languages,
            "name": body.name,
            "remark": body.remark,
            "reference_audio": body.reference_audio,
            "reference_text": body.reference_text,
            "sort": body.sort if body.sort is not None else 0,
            "tts_model_id": body.tts_model_id,
            "tts_voice": body.tts_voice,
            "voice_demo": body.voice_demo,
            "creator": user.id,
            "updater": user.id,
            "now": shanghai_now_naive(),
        }


_VALIDATION_FILES = {
    "zh-CN": "validation_zh_CN.properties",
    "zh-TW": "validation_zh_TW.properties",
    "en-US": "validation_en_US.properties",
    "de-DE": "validation_de_DE.properties",
    "vi-VN": "validation_vi_VN.properties",
    "pt-BR": "validation_pt_BR.properties",
}


@lru_cache(maxsize=64)
def _validation_message(key: str, accept_language: str | None) -> str:
    language = resolve_language(accept_language)
    directory = get_settings().i18n_dir
    messages = _load_properties(directory / "validation.properties")
    messages.update(_load_properties(directory / _VALIDATION_FILES[language]))
    return messages.get(key, key)
