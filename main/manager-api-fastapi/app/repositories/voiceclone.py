from __future__ import annotations

# Every interpolated SQL fragment below is a module constant or a service-side allowlist.
# ruff: noqa: S608
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Repository

VOICE_COLUMNS = (
    "id, name, model_id, voice_id, languages, user_id, voice, train_status, train_error, creator, create_date"
)


class VoiceCloneRepository(Repository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def count(self, *, name: str | None, user_id: str | None) -> int:
        where, params = self._filters(name=name, user_id=user_id)
        return int(await self.scalar(f"SELECT COUNT(*) FROM ai_voice_clone{where}", params) or 0)

    async def page(
        self,
        *,
        page: int,
        limit: int,
        name: str | None,
        user_id: str | None,
        order_fields: Sequence[str],
        ascending: bool,
    ) -> list[dict[str, Any]]:
        where, params = self._filters(name=name, user_id=user_id)
        params.update(limit=limit, offset=max(page - 1, 0) * limit)
        direction = "ASC" if ascending else "DESC"
        order_by = ", ".join(f"{field} {direction}" for field in order_fields)
        return await self.fetch_all(
            f"SELECT {VOICE_COLUMNS} FROM ai_voice_clone{where} "
            f"ORDER BY {order_by} LIMIT :limit OFFSET :offset",
            params,
        )

    async def get(self, voice_id: str | None) -> dict[str, Any] | None:
        if voice_id is None:
            return None
        return await self.fetch_one(
            f"SELECT {VOICE_COLUMNS} FROM ai_voice_clone WHERE id = :id LIMIT 1",
            {"id": voice_id},
        )

    async def list_by_user(self, user_id: int) -> list[dict[str, Any]]:
        return await self.fetch_all(
            f"SELECT {VOICE_COLUMNS} FROM ai_voice_clone "
            "WHERE user_id = :user_id ORDER BY create_date DESC",
            {"user_id": user_id},
        )

    async def voice_id_count(self, *, model_id: str, voice_id: str) -> int:
        return int(
            await self.scalar(
                "SELECT COUNT(*) FROM ai_voice_clone WHERE voice_id = :voice_id AND model_id = :model_id",
                {"model_id": model_id, "voice_id": voice_id},
            )
            or 0
        )

    async def insert_many(self, values: Sequence[Mapping[str, Any]]) -> int:
        return await self.execute_many(
            "INSERT INTO ai_voice_clone "
            "(id, name, model_id, voice_id, languages, user_id, voice, train_status, train_error, creator, "
            "create_date) VALUES (:id, :name, :model_id, :voice_id, :languages, :user_id, :voice, :train_status, "
            ":train_error, :creator, :create_date)",
            values,
        )

    async def delete_many(self, ids: Sequence[str]) -> int:
        if not ids:
            return 0
        placeholders = ", ".join(f":id_{index}" for index in range(len(ids)))
        params = {f"id_{index}": value for index, value in enumerate(ids)}
        return await self.execute(f"DELETE FROM ai_voice_clone WHERE id IN ({placeholders})", params)

    async def update_voice(self, voice_id: str, data: bytes) -> int:
        return await self.execute(
            "UPDATE ai_voice_clone SET voice = :voice, train_status = 0 WHERE id = :id",
            {"id": voice_id, "voice": data},
        )

    async def update_name(self, voice_id: str, name: str) -> int:
        return await self.execute(
            "UPDATE ai_voice_clone SET name = :name WHERE id = :id",
            {"id": voice_id, "name": name},
        )

    async def update_training(
        self,
        voice_id: str,
        *,
        train_status: int,
        train_error: str | None,
        speaker_id: str | None = None,
    ) -> int:
        if speaker_id is None:
            return await self.execute(
                "UPDATE ai_voice_clone SET train_status = :train_status, train_error = :train_error WHERE id = :id",
                {"id": voice_id, "train_status": train_status, "train_error": train_error},
            )
        return await self.execute(
            "UPDATE ai_voice_clone SET train_status = :train_status, train_error = :train_error, "
            "voice_id = :speaker_id WHERE id = :id",
            {
                "id": voice_id,
                "train_status": train_status,
                "train_error": train_error,
                "speaker_id": speaker_id,
            },
        )

    async def get_model_config(self, model_id: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT id, model_name, config_json FROM ai_model_config WHERE id = :id LIMIT 1",
            {"id": model_id},
        )

    async def get_model_name(self, model_id: str) -> str | None:
        value = await self.scalar(
            "SELECT model_name FROM ai_model_config WHERE id = :id LIMIT 1",
            {"id": model_id},
        )
        return None if value is None else str(value)

    async def get_usernames(self, user_ids: Sequence[int]) -> dict[int, str]:
        if not user_ids:
            return {}
        unique_ids = list(dict.fromkeys(user_ids))
        placeholders = ", ".join(f":user_{index}" for index in range(len(unique_ids)))
        params = {f"user_{index}": value for index, value in enumerate(unique_ids)}
        rows = await self.fetch_all(
            f"SELECT id, username FROM sys_user WHERE id IN ({placeholders})",
            params,
        )
        return {int(row["id"]): str(row["username"]) for row in rows}

    async def get_username(self, user_id: int) -> str | None:
        value = await self.scalar(
            "SELECT username FROM sys_user WHERE id = :id LIMIT 1",
            {"id": user_id},
        )
        return None if value is None else str(value)

    async def get_tts_platforms(self) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT id, model_name AS modelName FROM ai_model_config "
            "WHERE model_type = 'TTS' AND JSON_EXTRACT(config_json, '$.type') = 'huoshan_double_stream'"
        )

    @staticmethod
    def _filters(*, name: str | None, user_id: str | None) -> tuple[str, dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if user_id is not None and user_id.strip():
            clauses.append("user_id = :user_id")
            params["user_id"] = user_id
        if name is not None and name.strip():
            clauses.append("(name LIKE :name OR voice_id = :exact_name)")
            params["name"] = f"%{name}%"
            params["exact_name"] = name
        return (" WHERE " + " AND ".join(clauses) if clauses else "", params)
