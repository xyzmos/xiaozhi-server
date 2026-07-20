from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Repository


class CorrectWordRepository(Repository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def name_exists(self, user_id: int, file_name: str, exclude_id: str | None = None) -> bool:
        return bool(
            await self.scalar(
                "SELECT COUNT(*) FROM ai_agent_correct_word_file WHERE creator=:creator AND file_name=:file_name "
                "AND (:exclude_id IS NULL OR id<>:exclude_id)",
                {"creator": user_id, "file_name": file_name, "exclude_id": exclude_id},
            )
        )

    async def insert_file(self, values: dict[str, Any]) -> None:
        await self.execute(
            "INSERT INTO ai_agent_correct_word_file "
            "(id, file_name, word_count, content, creator, created_at) "
            "VALUES (:id, :file_name, :word_count, :content, :creator, :now)",
            values,
        )

    async def insert_items(self, values: Sequence[dict[str, Any]]) -> None:
        await self.execute_many(
            "INSERT INTO ai_agent_correct_word_item (id, file_id, source_word, target_word) "
            "VALUES (:id, :file_id, :source_word, :target_word)",
            values,
        )

    async def get_file(self, file_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
        suffix = " FOR UPDATE" if for_update and self.session.get_bind().dialect.name != "sqlite" else ""
        return await self.fetch_one(
            f"SELECT * FROM ai_agent_correct_word_file WHERE id=:id{suffix}",  # noqa: S608
            {"id": file_id},
        )

    async def update_file(self, values: dict[str, Any]) -> int:
        return await self.execute(
            "UPDATE ai_agent_correct_word_file SET file_name=:file_name, word_count=:word_count, "
            "content=:content, updater=:updater, updated_at=:now WHERE id=:id",
            values,
        )

    async def list_files(
        self, user_id: int, *, offset: int | None = None, limit: int | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        total = int(
            await self.scalar(
                "SELECT COUNT(*) FROM ai_agent_correct_word_file WHERE creator=:creator", {"creator": user_id}
            )
            or 0
        )
        if offset is None or limit is None:
            rows = await self.fetch_all(
                "SELECT * FROM ai_agent_correct_word_file WHERE creator=:creator ORDER BY created_at DESC",
                {"creator": user_id},
            )
        else:
            rows = await self.fetch_all(
                "SELECT * FROM ai_agent_correct_word_file WHERE creator=:creator ORDER BY created_at DESC "
                "LIMIT :offset, :limit",
                {"creator": user_id, "offset": offset, "limit": limit},
            )
        return rows, total

    async def delete_file_graph(self, file_id: str) -> None:
        await self.execute("DELETE FROM ai_agent_correct_word_mapping WHERE file_id=:id", {"id": file_id})
        await self.execute("DELETE FROM ai_agent_correct_word_item WHERE file_id=:id", {"id": file_id})
        await self.execute("DELETE FROM ai_agent_correct_word_file WHERE id=:id", {"id": file_id})

    async def delete_items(self, file_id: str) -> None:
        await self.execute("DELETE FROM ai_agent_correct_word_item WHERE file_id=:id", {"id": file_id})

    async def items_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT i.source_word, i.target_word FROM ai_agent_correct_word_item i "
            "JOIN ai_agent_correct_word_mapping m ON m.file_id=i.file_id WHERE m.agent_id=:agent_id",
            {"agent_id": agent_id},
        )

    async def file_ids_for_agent(self, agent_id: str) -> list[str]:
        rows = await self.fetch_all(
            "SELECT file_id FROM ai_agent_correct_word_mapping WHERE agent_id=:agent_id", {"agent_id": agent_id}
        )
        return [str(row["file_id"]) for row in rows]

    async def replace_agent_mappings(
        self, agent_id: str, file_ids: Sequence[str], user_id: int, now: Any
    ) -> None:
        await self.execute("DELETE FROM ai_agent_correct_word_mapping WHERE agent_id=:agent_id", {"agent_id": agent_id})
        await self.execute_many(
            "INSERT INTO ai_agent_correct_word_mapping "
            "(id, agent_id, file_id, creator, created_at, updater, updated_at) "
            "VALUES (:id, :agent_id, :file_id, :user_id, :now, :user_id, :now)",
            [
                {
                    "id": uuid.uuid4().hex,
                    "agent_id": agent_id,
                    "file_id": file_id,
                    "user_id": user_id,
                    "now": now,
                }
                for file_id in file_ids
            ],
        )
