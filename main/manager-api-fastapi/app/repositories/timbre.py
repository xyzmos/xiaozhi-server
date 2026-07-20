from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Repository


class TimbreRepository(Repository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def page(
        self, *, tts_model_id: str, name: str | None, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        where = (
            "WHERE tts_model_id=:tts_model_id AND "
            "(:name IS NULL OR :name='' OR name LIKE CONCAT('%', :name, '%'))"
        )
        params = {"tts_model_id": tts_model_id, "name": name, "offset": offset, "limit": limit}
        total = int(await self.scalar(f"SELECT COUNT(*) FROM ai_tts_voice {where}", params) or 0)  # noqa: S608
        rows = await self.fetch_all(
            f"SELECT * FROM ai_tts_voice {where} LIMIT :offset, :limit",  # noqa: S608
            params,
        )
        return rows, total

    async def insert(self, values: dict[str, Any]) -> None:
        await self.execute(
            "INSERT INTO ai_tts_voice "
            "(id, languages, name, remark, reference_audio, reference_text, sort, tts_model_id, tts_voice, "
            "voice_demo, creator, create_date) VALUES (:id, :languages, :name, :remark, :reference_audio, "
            ":reference_text, :sort, :tts_model_id, :tts_voice, :voice_demo, :creator, :now)",
            values,
        )

    async def update(self, values: dict[str, Any]) -> int:
        return await self.execute(
            "UPDATE ai_tts_voice SET languages=:languages, name=:name, remark=COALESCE(:remark, remark), "
            "reference_audio=COALESCE(:reference_audio, reference_audio), "
            "reference_text=COALESCE(:reference_text, reference_text), sort=:sort, "
            "tts_model_id=:tts_model_id, tts_voice=:tts_voice, "
            "voice_demo=COALESCE(:voice_demo, voice_demo), updater=:updater, "
            "update_date=:now WHERE id=:id",
            values,
        )

    async def delete(self, ids: Sequence[str]) -> int:
        if not ids:
            return 0
        statement = text("DELETE FROM ai_tts_voice WHERE id IN :ids").bindparams(bindparam("ids", expanding=True))
        result = await self.session.execute(statement, {"ids": list(ids)})
        return int(getattr(result, "rowcount", 0) or 0)

    async def voices(
        self, model_id: str, name: str | None, user_id: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        normal = await self.fetch_all(
            "SELECT id, name, voice_demo, languages FROM ai_tts_voice WHERE tts_model_id=:model_id "
            "AND (:name IS NULL OR :name='' OR name LIKE CONCAT('%', :name, '%'))",
            {"model_id": model_id or "", "name": name},
        )
        clones = await self.fetch_all(
            "SELECT id, name, voice_id AS voice_demo, languages FROM ai_voice_clone "
            "WHERE model_id=:model_id AND user_id=:user_id AND train_status=2",
            {"model_id": model_id, "user_id": user_id},
        )
        return normal, clones
