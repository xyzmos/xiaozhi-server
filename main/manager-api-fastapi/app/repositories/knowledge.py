from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import Repository


class KnowledgeRepository(Repository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def dataset_page(
        self, user_id: int, name: str | None, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        where = (
            "WHERE creator=:creator AND (:name IS NULL OR :name='' OR name LIKE CONCAT('%', :name, '%'))"
        )
        params = {"creator": user_id, "name": name, "offset": offset, "limit": limit}
        total = int(await self.scalar(f"SELECT COUNT(*) FROM ai_rag_dataset {where}", params) or 0)  # noqa: S608
        rows = await self.fetch_all(
            f"SELECT * FROM ai_rag_dataset {where} ORDER BY created_at DESC LIMIT :offset, :limit",  # noqa: S608
            params,
        )
        return rows, total

    async def get_dataset(self, identifier: str, *, for_update: bool = False) -> dict[str, Any] | None:
        suffix = " FOR UPDATE" if for_update and self.session.get_bind().dialect.name != "sqlite" else ""
        return await self.fetch_one(
            f"SELECT * FROM ai_rag_dataset WHERE dataset_id=:id OR id=:id LIMIT 1{suffix}",  # noqa: S608
            {"id": identifier},
        )

    async def datasets_by_ids(self, identifiers: Sequence[str]) -> list[dict[str, Any]]:
        if not identifiers:
            return []
        statement = text("SELECT * FROM ai_rag_dataset WHERE dataset_id IN :ids OR id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        )
        result = await self.session.execute(statement, {"ids": list(identifiers)})
        return [dict(row) for row in result.mappings().all()]

    async def duplicate_dataset_name(self, user_id: int, name: str, exclude_id: str | None = None) -> bool:
        return bool(
            await self.scalar(
                "SELECT COUNT(*) FROM ai_rag_dataset WHERE creator=:creator AND name=:name "
                "AND (:exclude_id IS NULL OR id<>:exclude_id)",
                {"creator": user_id, "name": name, "exclude_id": exclude_id},
            )
        )

    async def dataset_id_conflict(self, dataset_id: str, exclude_id: str) -> bool:
        return bool(
            await self.scalar(
                "SELECT COUNT(*) FROM ai_rag_dataset WHERE dataset_id=:dataset_id AND id<>:exclude_id",
                {"dataset_id": dataset_id, "exclude_id": exclude_id},
            )
        )

    async def insert_dataset(self, values: dict[str, Any]) -> None:
        await self.execute(
            "INSERT INTO ai_rag_dataset "
            "(id,dataset_id,rag_model_id,tenant_id,name,avatar,description,embedding_model,permission,chunk_method,"
            "parser_config,chunk_count,document_count,token_num,status,creator,created_at,updater,updated_at) VALUES "
            "(:id,:dataset_id,:rag_model_id,:tenant_id,:name,:avatar,:description,:embedding_model,:permission,"
            ":chunk_method,:parser_config,:chunk_count,:document_count,:token_num,:status,:creator,:created_at,"
            ":updater,:updated_at)",
            values,
        )

    async def update_dataset(self, values: dict[str, Any]) -> int:
        return await self.execute(
            "UPDATE ai_rag_dataset SET dataset_id=COALESCE(:dataset_id,dataset_id),"
            "rag_model_id=COALESCE(:rag_model_id,rag_model_id),name=COALESCE(:name,name),"
            "avatar=COALESCE(:avatar,avatar),description=COALESCE(:description,description),"
            "embedding_model=COALESCE(:embedding_model,embedding_model),"
            "permission=COALESCE(:permission,permission),chunk_method=COALESCE(:chunk_method,chunk_method),"
            "parser_config=COALESCE(:parser_config,parser_config),chunk_count=COALESCE(:chunk_count,chunk_count),"
            "token_num=COALESCE(:token_num,token_num),status=COALESCE(:status,status),"
            "creator=COALESCE(:creator,creator),created_at=COALESCE(:created_at,created_at),updater=:updater,"
            "updated_at=:updated_at WHERE id=:id",
            values,
        )

    async def delete_dataset_local(self, row: dict[str, Any]) -> None:
        await self.execute("DELETE FROM ai_agent_plugin_mapping WHERE plugin_id=:id", {"id": row["id"]})
        await self.execute("DELETE FROM ai_rag_dataset WHERE id=:id", {"id": row["id"]})

    async def rag_models(self) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT id, model_name, config_json FROM ai_model_config WHERE model_type='RAG' AND is_enabled=1 "
            "ORDER BY is_default DESC, create_date DESC"
        )

    async def rag_config(self, model_id: str) -> dict[str, Any]:
        row = await self.fetch_one("SELECT config_json FROM ai_model_config WHERE id=:id", {"id": model_id})
        if row is None or row.get("config_json") is None:
            from app.core.errors import AppError

            raise AppError(10164)
        raw = row["config_json"]
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        config = dict(raw) if isinstance(raw, dict) else dict(json.loads(str(raw)))
        config.setdefault("type", "ragflow")
        return config

    async def documents_page(
        self,
        dataset_id: str,
        *,
        name: str | None,
        status: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        where = (
            "WHERE dataset_id=:dataset_id "
            "AND (:name IS NULL OR :name='' OR name LIKE CONCAT('%', :name, '%')) "
            "AND (:status IS NULL OR :status='' OR status=:status)"
        )
        params = {"dataset_id": dataset_id, "name": name, "status": status, "offset": offset, "limit": limit}
        total = int(await self.scalar(f"SELECT COUNT(*) FROM ai_rag_knowledge_document {where}", params) or 0)  # noqa: S608
        rows = await self.fetch_all(
            f"SELECT * FROM ai_rag_knowledge_document {where} "  # noqa: S608
            "ORDER BY created_at DESC LIMIT :offset, :limit",
            params,
        )
        return rows, total

    async def all_documents(self, dataset_id: str) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT * FROM ai_rag_knowledge_document WHERE dataset_id=:dataset_id", {"dataset_id": dataset_id}
        )

    async def documents_by_remote_ids(self, dataset_id: str, ids: Sequence[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        statement = text(
            "SELECT * FROM ai_rag_knowledge_document WHERE dataset_id=:dataset_id AND document_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        result = await self.session.execute(statement, {"dataset_id": dataset_id, "ids": list(ids)})
        return [dict(row) for row in result.mappings().all()]

    async def upsert_document(self, dataset_id: str, remote: dict[str, Any], *, creator: int | None = None) -> bool:
        document_id = str(remote.get("id") or remote.get("document_id") or "")
        existing = await self.fetch_one(
            "SELECT id,created_at FROM ai_rag_knowledge_document WHERE document_id=:id", {"id": document_id}
        )
        name = remote.get("name")
        size = remote.get("size")
        if size is None:
            size = remote.get("file_size")
        meta_fields = remote.get("meta_fields")
        if meta_fields is None:
            meta_fields = remote.get("meta")
        error = remote.get("progress_msg")
        if error is None:
            error = remote.get("error")
        synced_at = _shanghai_now_naive()
        created_at = remote.get("created_at")
        if not isinstance(created_at, datetime):
            created_at = _millis_date(remote.get("create_time"))
        updated_at = remote.get("updated_at")
        if not isinstance(updated_at, datetime):
            updated_at = _millis_date(remote.get("update_time"))
        values = {
            "id": existing["id"] if existing else uuid.uuid4().hex,
            "dataset_id": remote.get("dataset_id") or dataset_id,
            "document_id": document_id,
            "name": name,
            "size": size,
            "type": _file_type(str(name or "")),
            "chunk_method": remote.get("chunk_method"),
            "parser_config": _json_dump(remote.get("parser_config")),
            "status": _remote_status(remote.get("status")),
            "run": remote.get("run"),
            "progress": remote.get("progress"),
            "thumbnail": remote.get("thumbnail"),
            "process_duration": remote.get("process_duration"),
            "meta_fields": _json_dump(meta_fields),
            "source_type": remote.get("source_type"),
            "error": error,
            "chunk_count": remote.get("chunk_count") or 0,
            "token_count": remote.get("token_count") or 0,
            "enabled": 1,
            "creator": creator,
            "created_at": existing.get("created_at") if existing else (created_at or synced_at),
            "updated_at": updated_at or synced_at,
            "synced_at": synced_at,
        }
        if existing:
            await self.execute(
                "UPDATE ai_rag_knowledge_document SET dataset_id=:dataset_id,document_id=:document_id,name=:name,"
                "size=:size,type=:type,chunk_method=:chunk_method,parser_config=:parser_config,status=:status,run=:run,"
                "progress=:progress,thumbnail=:thumbnail,process_duration=:process_duration,meta_fields=:meta_fields,"
                "source_type=:source_type,error=:error,chunk_count=:chunk_count,token_count=:token_count,enabled=:enabled,"
                "updated_at=:updated_at,last_sync_at=:synced_at WHERE id=:id",
                values,
            )
            return False
        await self.execute(
            "INSERT INTO ai_rag_knowledge_document "
            "(id,dataset_id,document_id,name,size,type,chunk_method,parser_config,status,run,progress,thumbnail,"
            "process_duration,meta_fields,source_type,error,chunk_count,token_count,enabled,creator,created_at,updated_at,"
            "last_sync_at) VALUES (:id,:dataset_id,:document_id,:name,:size,:type,:chunk_method,:parser_config,:status,"
            ":run,:progress,:thumbnail,:process_duration,:meta_fields,:source_type,:error,:chunk_count,:token_count,"
            ":enabled,:creator,COALESCE(:created_at,:synced_at),COALESCE(:updated_at,:synced_at),:synced_at)",
            values,
        )
        return True

    async def update_stats(self, dataset_id: str, docs: int, chunks: int, tokens: int) -> None:
        await self.execute(
            "UPDATE ai_rag_dataset SET document_count=document_count+:docs,chunk_count=chunk_count+:chunks,"
            "token_num=token_num+:tokens,updated_at=:now WHERE dataset_id=:dataset_id",
            {
                "dataset_id": dataset_id,
                "docs": docs,
                "chunks": chunks,
                "tokens": tokens,
                "now": _shanghai_now_naive(),
            },
        )

    async def delete_document_shadows(self, dataset_id: str, ids: Sequence[str]) -> int:
        if not ids:
            return 0
        statement = text(
            "DELETE FROM ai_rag_knowledge_document WHERE dataset_id=:dataset_id AND document_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        result = await self.session.execute(statement, {"dataset_id": dataset_id, "ids": list(ids)})
        return int(getattr(result, "rowcount", 0) or 0)

    async def mark_documents_running(self, dataset_id: str, ids: Sequence[str], now: datetime) -> int:
        if not ids:
            return 0
        statement = text(
            "UPDATE ai_rag_knowledge_document SET run='RUNNING',status='1',updated_at=:now "
            "WHERE dataset_id=:dataset_id AND document_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        result = await self.session.execute(statement, {"dataset_id": dataset_id, "ids": list(ids), "now": now})
        return int(getattr(result, "rowcount", 0) or 0)

    async def mark_document_remote_deleted(self, document_id: str, now: datetime) -> int:
        return await self.execute(
            "UPDATE ai_rag_knowledge_document SET run='CANCEL',error=:error,updated_at=:now,last_sync_at=:now "
            "WHERE document_id=:document_id",
            {
                "document_id": document_id,
                "error": "文档在远程服务中已被删除",
                "now": now,
            },
        )

    async def sync_running_document(
        self,
        dataset_id: str,
        document_id: str,
        remote: dict[str, Any],
        now: datetime,
    ) -> int:
        """Update exactly the columns touched by Java's status-sync helper."""
        updated_at = _millis_date(remote.get("update_time")) or now
        meta_fields = remote.get("meta_fields")
        assignments = (
            "status=:status,run=:run,progress=:progress,chunk_count=:chunk_count,token_count=:token_count,"
            "error=:error,process_duration=:process_duration,thumbnail=:thumbnail,updated_at=:updated_at,"
            "last_sync_at=:now"
        )
        if meta_fields is not None:
            assignments += ",meta_fields=:meta_fields"
        return await self.execute(
            f"UPDATE ai_rag_knowledge_document SET {assignments} "  # noqa: S608
            "WHERE document_id=:document_id AND dataset_id=:dataset_id",
            {
                "dataset_id": dataset_id,
                "document_id": document_id,
                "status": remote.get("status"),
                "run": remote.get("run"),
                "progress": remote.get("progress"),
                "chunk_count": remote.get("chunk_count"),
                "token_count": remote.get("token_count"),
                "error": remote.get("progress_msg") if remote.get("progress_msg") is not None else remote.get("error"),
                "process_duration": remote.get("process_duration"),
                "thumbnail": remote.get("thumbnail"),
                "meta_fields": _json_dump(meta_fields),
                "updated_at": updated_at,
                "now": now,
            },
        )

    async def running_documents(self) -> list[dict[str, Any]]:
        return await self.fetch_all("SELECT * FROM ai_rag_knowledge_document WHERE run='RUNNING' AND status='1'")


def _json_dump(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _millis_date(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        timezone = ZoneInfo(get_settings().timezone)
        return datetime.fromtimestamp(float(value) / 1000, timezone).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


def _file_type(name: str) -> str:
    last_dot = name.rfind(".")
    if last_dot <= 0 or last_dot == len(name) - 1:
        return "unknown"
    extension = name.rsplit(".", 1)[1].lower()
    if extension in {"pdf", "doc", "docx", "txt", "md", "mdx"}:
        return "document"
    if extension in {"csv", "xls", "xlsx"}:
        return "spreadsheet"
    if extension in {"ppt", "pptx"}:
        return "presentation"
    return extension


def _remote_status(value: Any) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "1"
    return str(value)


def _shanghai_now_naive() -> datetime:
    return datetime.now(ZoneInfo(get_settings().timezone)).replace(tzinfo=None)
