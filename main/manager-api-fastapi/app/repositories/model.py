from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Repository


class ModelRepository(Repository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def list_model_names(self, model_type: str, model_name: str | None) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT id, model_name FROM ai_model_config "
            "WHERE model_type = :model_type AND is_enabled = 1 "
            "AND (:model_name IS NULL OR :model_name = '' OR model_name LIKE CONCAT('%', :model_name, '%')) "
            "ORDER BY sort ASC",
            {"model_type": model_type, "model_name": model_name},
        )

    async def list_llm_names(self, model_name: str | None) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT id, model_name, config_json FROM ai_model_config "
            "WHERE model_type = 'llm' AND is_enabled = 1 "
            "AND (:model_name IS NULL OR :model_name = '' OR model_name LIKE CONCAT('%', :model_name, '%'))",
            {"model_name": model_name},
        )

    async def list_providers_by_type(self, model_type: str) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT * FROM ai_model_provider WHERE model_type = :model_type ORDER BY sort ASC",
            {"model_type": model_type or ""},
        )

    async def list_providers(
        self,
        *,
        model_type: str | None,
        name: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        where = (
            "WHERE (:model_type IS NULL OR :model_type = '' OR model_type = :model_type) "
            "AND (:name IS NULL OR :name = '' OR name LIKE CONCAT('%', :name, '%') "
            "OR provider_code LIKE CONCAT('%', :name, '%'))"
        )
        params = {"model_type": model_type, "name": name, "offset": offset, "limit": limit}
        total = int(await self.scalar(f"SELECT COUNT(*) FROM ai_model_provider {where}", params) or 0)  # noqa: S608
        rows = await self.fetch_all(
            f"SELECT * FROM ai_model_provider {where} "  # noqa: S608
            "ORDER BY model_type ASC, sort ASC LIMIT :offset, :limit",
            params,
        )
        return rows, total

    async def list_model_configs(
        self,
        *,
        model_type: str,
        model_name: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        where = (
            "WHERE model_type = :model_type AND "
            "(:model_name IS NULL OR :model_name = '' OR model_name LIKE CONCAT('%', :model_name, '%'))"
        )
        params = {"model_type": model_type, "model_name": model_name, "offset": offset, "limit": limit}
        total = int(await self.scalar(f"SELECT COUNT(*) FROM ai_model_config {where}", params) or 0)  # noqa: S608
        rows = await self.fetch_all(
            f"SELECT * FROM ai_model_config {where} "  # noqa: S608
            "ORDER BY is_enabled DESC, sort ASC LIMIT :offset, :limit",
            params,
        )
        return rows, total

    async def get_provider(self, model_type: str, provider_code: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT * FROM ai_model_provider WHERE model_type = :model_type AND provider_code = :provider_code LIMIT 1",
            {"model_type": model_type or "", "provider_code": provider_code or ""},
        )

    async def get_model(self, model_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
        suffix = " FOR UPDATE" if for_update and self.session.get_bind().dialect.name != "sqlite" else ""
        return await self.fetch_one(
            f"SELECT * FROM ai_model_config WHERE id = :id LIMIT 1{suffix}",  # noqa: S608
            {"id": model_id},
        )

    async def insert_model(self, values: dict[str, Any]) -> None:
        await self.execute(
            "INSERT INTO ai_model_config "
            "(id, model_type, model_code, model_name, is_default, is_enabled, config_json, doc_link, remark, sort) "
            "VALUES (:id, :model_type, :model_code, :model_name, :is_default, COALESCE(:is_enabled, 0), "
            ":config_json, :doc_link, :remark, COALESCE(:sort, 0))",
            values,
        )

    async def update_model(self, values: dict[str, Any]) -> int:
        return await self.execute(
            "UPDATE ai_model_config SET model_type=:model_type, model_code=:model_code, "
            "model_name=COALESCE(:model_name, model_name), is_default=:is_default, "
            "is_enabled=COALESCE(:is_enabled, is_enabled), config_json=:config_json, doc_link=:doc_link, "
            "remark=COALESCE(:remark, remark), sort=COALESCE(:sort, sort) WHERE id=:id",
            values,
        )

    async def delete_model(self, model_id: str) -> int:
        return await self.execute("DELETE FROM ai_model_config WHERE id = :id", {"id": model_id})

    async def model_agent_references(self, model_id: str) -> list[str]:
        rows = await self.fetch_all(
            "SELECT agent_name FROM ai_agent WHERE vad_model_id=:id OR asr_model_id=:id OR llm_model_id=:id "
            "OR tts_model_id=:id OR mem_model_id=:id OR vllm_model_id=:id OR intent_model_id=:id",
            {"id": model_id},
        )
        return [str(row.get("agent_name") or "") for row in rows]

    async def intent_reference_count(self, model_id: str) -> int:
        return int(
            await self.scalar(
                "SELECT COUNT(*) FROM ai_model_config WHERE model_type='Intent' AND CAST(config_json AS CHAR) LIKE "
                "CONCAT('%', :id, '%')",
                {"id": model_id},
            )
            or 0
        )

    async def set_models_default(self, model_type: str, value: int) -> None:
        await self.execute(
            "UPDATE ai_model_config SET is_default=:value WHERE model_type=:model_type",
            {"value": value, "model_type": model_type},
        )

    async def set_model_enabled(self, model_id: str, status: int) -> int:
        return await self.execute(
            "UPDATE ai_model_config SET is_enabled=:status WHERE id=:id",
            {"status": status, "id": model_id},
        )

    async def update_default_template_models(self, model_type: str, model_id: str) -> None:
        columns = {
            "ASR": ("asr_model_id",),
            "VAD": ("vad_model_id",),
            "LLM": ("llm_model_id",),
            "TTS": ("tts_model_id", "tts_voice_id"),
            "VLLM": ("vllm_model_id",),
            "MEMORY": ("mem_model_id",),
            "INTENT": ("intent_model_id",),
        }.get(model_type.upper())
        if not columns:
            return
        if columns == ("tts_model_id", "tts_voice_id"):
            await self.execute(
                "UPDATE ai_agent_template SET tts_model_id=:id, tts_voice_id=NULL WHERE sort >= 0",
                {"id": model_id},
            )
        else:
            column = columns[0]
            await self.session.execute(
                text(f"UPDATE ai_agent_template SET {column}=:id WHERE sort >= 0"),  # noqa: S608
                {"id": model_id},
            )

    async def insert_provider(self, values: dict[str, Any]) -> None:
        if self.session.get_bind().dialect.name == "sqlite":
            statement = (
                "INSERT INTO ai_model_provider "
                "(id, model_type, provider_code, name, fields, sort, creator, create_date, updater, update_date) "
                "VALUES (:id, :model_type, :provider_code, :name, :fields, :sort, :creator, :now, :updater, :now)"
            )
        else:
            statement = (
                "INSERT INTO ai_model_provider "
                "(id, model_type, provider_code, name, fields, sort, creator, create_date, updater, update_date) "
                "VALUES (:id, :model_type, :provider_code, :name, CAST(:fields AS JSON), :sort, :creator, :now, "
                ":updater, :now)"
            )
        await self.execute(statement, values)

    async def update_provider(self, values: dict[str, Any]) -> int:
        if self.session.get_bind().dialect.name == "sqlite":
            statement = (
                "UPDATE ai_model_provider SET model_type=:model_type, provider_code=:provider_code, name=:name, "
                "fields=:fields, sort=:sort, updater=:updater, update_date=:now WHERE id=:id"
            )
        else:
            statement = (
                "UPDATE ai_model_provider SET model_type=:model_type, provider_code=:provider_code, name=:name, "
                "fields=CAST(:fields AS JSON), sort=:sort, updater=:updater, update_date=:now WHERE id=:id"
            )
        return await self.execute(statement, values)

    async def delete_providers(self, ids: Sequence[str]) -> int:
        if not ids:
            return 0
        statement = text("DELETE FROM ai_model_provider WHERE id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        )
        result = await self.session.execute(statement, {"ids": list(ids)})
        return int(getattr(result, "rowcount", 0) or 0)

    async def list_plugins_for_user(self, user_id: int) -> list[dict[str, Any]]:
        providers = await self.fetch_all("SELECT * FROM ai_model_provider WHERE model_type='Plugin'")
        datasets = await self.fetch_all(
            "SELECT id, name, created_at, updated_at FROM ai_rag_dataset WHERE creator=:creator AND status=1",
            {"creator": user_id},
        )
        providers.extend(
            {
                "id": row["id"],
                "model_type": "Rag",
                "name": f"[知识库]{row['name']}",
                "provider_code": "ragflow",
                "fields": "[]",
                "sort": 0,
                "create_date": row.get("created_at"),
                "update_date": row.get("updated_at"),
                "creator": 0,
                "updater": 0,
            }
            for row in datasets
        )
        return providers


def parse_json_object(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        parsed = json.loads(value)
        return dict(parsed) if isinstance(parsed, dict) else None
    return None
