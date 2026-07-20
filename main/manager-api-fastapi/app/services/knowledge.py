from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.i18n import message_for
from app.core.redis import get_redis
from app.core.security import AuthUser, shanghai_now_naive
from app.core.serialization import preserve_java_map_keys
from app.integrations.ragflow import RAGFlowClient
from app.repositories.knowledge import KnowledgeRepository
from app.schemas.knowledge import KnowledgeBaseBody, RetrievalBody


def dataset_dto(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "datasetId": row.get("dataset_id"),
        "ragModelId": row.get("rag_model_id"),
        "name": row.get("name"),
        "avatar": row.get("avatar"),
        "description": row.get("description"),
        "embeddingModel": row.get("embedding_model"),
        "permission": row.get("permission"),
        "chunkMethod": row.get("chunk_method"),
        "parserConfig": row.get("parser_config"),
        "chunkCount": None if row.get("chunk_count") is None else str(row["chunk_count"]),
        "tokenNum": None if row.get("token_num") is None else str(row["token_num"]),
        "status": row.get("status"),
        "creator": row.get("creator"),
        "createdAt": row.get("created_at"),
        "updater": row.get("updater"),
        "updatedAt": row.get("updated_at"),
        # KnowledgeBaseEntity.documentCount is Long while KnowledgeBaseDTO uses
        # Integer. Spring BeanUtils does not coerce that property, so local DTO
        # conversion leaves it null; list enrichment fills it from RAGFlow.
        "documentCount": None,
        "errorMessage": row.get("error_message"),
    }


def document_dto(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("document_id"),
        "documentId": row.get("document_id"),
        "datasetId": row.get("dataset_id"),
        "name": row.get("name"),
        # RAGFlowAdapter.mapToKnowledgeFilesDTO does not populate these two
        # fields for the immediate upload response.
        "fileType": None,
        "fileSize": row.get("size"),
        "filePath": None,
        "progress": row.get("progress"),
        "thumbnail": row.get("thumbnail"),
        "processDuration": row.get("process_duration"),
        "sourceType": row.get("source_type"),
        "metaFields": _json_object(row.get("meta_fields")),
        "chunkMethod": row.get("chunk_method"),
        "parserConfig": _json_object(row.get("parser_config")),
        "status": row.get("status"),
        "run": row.get("run"),
        "creator": row.get("creator"),
        "createdAt": row.get("created_at"),
        "updater": None,
        "updatedAt": row.get("updated_at"),
        "chunkCount": row.get("chunk_count"),
        "tokenCount": row.get("token_count"),
        "error": row.get("error"),
        "parseStatusCode": _parse_status(row.get("run")),
    }


def remote_document_dto(row: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    run = row.get("run")
    return {
        "id": row.get("id"),
        "documentId": row.get("id"),
        "datasetId": row.get("dataset_id") or dataset_id,
        "name": row.get("name"),
        "fileType": row.get("type"),
        "fileSize": row.get("size"),
        "filePath": None,
        "progress": row.get("progress"),
        "thumbnail": row.get("thumbnail"),
        "processDuration": row.get("process_duration"),
        "sourceType": row.get("source_type"),
        "metaFields": row.get("meta_fields"),
        "chunkMethod": row.get("chunk_method"),
        "parserConfig": row.get("parser_config"),
        "status": _remote_status(row.get("status")),
        "run": run,
        "creator": None,
        "createdAt": _millis(row.get("create_time")),
        "updater": None,
        "updatedAt": _millis(row.get("update_time")),
        "chunkCount": row.get("chunk_count") or 0,
        "tokenCount": row.get("token_count"),
        "error": row.get("progress_msg"),
        "parseStatusCode": _parse_status(run),
    }


def _parse_status(run: Any) -> int:
    return {"RUNNING": 1, "CANCEL": 2, "DONE": 3, "FAIL": 4}.get(str(run or "").upper(), 0)


def _json_object(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(value.decode() if isinstance(value, bytes) else str(value))
        return dict(parsed) if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        return None


def _millis(value: Any) -> Any:
    try:
        if value is None:
            return None
        timezone = ZoneInfo(get_settings().timezone)
        return datetime.fromtimestamp(float(value) / 1000, timezone).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


def _is_blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _remote_status(value: Any) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "1"
    return str(value)


class KnowledgeBaseService:
    def __init__(self, repository: KnowledgeRepository):
        self.repository = repository

    async def get_owned(self, identifier: str, user: AuthUser) -> dict[str, Any]:
        if not identifier.strip():
            raise AppError(10003)
        row = await self.repository.get_dataset(identifier)
        if row is None:
            raise AppError(10163)
        if row.get("creator") is None or int(row["creator"]) != user.id:
            raise AppError(10169)
        return row

    async def page(
        self,
        user: AuthUser,
        name: str | None,
        page: int,
        page_size: int,
        language: str | None = None,
    ) -> dict[str, Any]:
        rows, total = await self.repository.dataset_page(
            user.id, name, (max(page, 1) - 1) * page_size, page_size
        )
        results: list[dict[str, Any]] = []
        changed = False
        for row in rows:
            dto = dataset_dto(row)
            if row.get("dataset_id") and row.get("rag_model_id"):
                try:
                    client = await self._client(str(row["rag_model_id"]))
                    remote = await client.dataset_info(str(row["dataset_id"]))
                    if remote is None:
                        await self.repository.execute(
                            "DELETE FROM ai_rag_knowledge_document WHERE dataset_id=:dataset_id",
                            {"dataset_id": row["dataset_id"]},
                        )
                        await self.repository.delete_dataset_local(row)
                        await _delete_cache_ignoring_errors(f"knowledge:base:{row['id']}")
                        changed = True
                        continue
                    remote_name = remote.get("name")
                    local_name = (
                        str(remote_name).split("_", 1)[1]
                        if remote_name and "_" in str(remote_name)
                        else remote_name
                    )
                    updates: dict[str, Any] = {}
                    if local_name and local_name != row.get("name"):
                        updates["name"] = local_name
                        dto["name"] = local_name
                    if remote.get("description") != row.get("description"):
                        updates["description"] = remote.get("description")
                        dto["description"] = remote.get("description")
                    if updates:
                        await self.repository.execute(
                            "UPDATE ai_rag_dataset SET name=COALESCE(:name,name),description=:description WHERE id=:id",
                            {
                                "name": updates.get("name"),
                                "description": updates.get("description", row.get("description")),
                                "id": row["id"],
                            },
                        )
                        changed = True
                    if remote.get("document_count") is not None:
                        dto["documentCount"] = int(remote["document_count"])
                except Exception as exc:
                    dto["documentCount"] = 0
                    dto["errorMessage"] = (
                        message_for(exc.code, language, *exc.params)
                        if isinstance(exc, AppError)
                        else str(exc)
                    )
            results.append(dto)
        if changed:
            await self.repository.session.commit()
        return {"total": total, "list": results}

    async def create(self, body: KnowledgeBaseBody, user: AuthUser) -> dict[str, Any]:
        if not _is_blank(body.name) and await self.repository.duplicate_dataset_name(user.id, str(body.name)):
            raise AppError(10170)
        rag_model_id = body.rag_model_id
        if _is_blank(rag_model_id):
            models = await self.repository.rag_models()
            if not models:
                raise AppError(10164, params=("未指定且无可用默认 RAG 模型",))
            rag_model_id = str(models[0]["id"])
        client = await self._client(str(rag_model_id))
        create_body = {
            "name": f"{user.username}_{'null' if body.name is None else body.name}",
            "avatar": body.avatar,
            "description": body.description,
            "embedding_model": body.embedding_model,
            "permission": body.permission,
            "chunk_method": body.chunk_method,
            # KnowledgeBaseDTO.parserConfig is a String, while CreateReq uses
            # ParserConfig. BeanUtils skips the incompatible property.
            "parser_config": None,
        }
        remote = await client.create_dataset(create_body)
        dataset_id = str(remote["id"])
        now = shanghai_now_naive()
        created_at = body.created_at or now
        updated_at = body.updated_at or now
        values = {
            "id": dataset_id,
            "dataset_id": dataset_id,
            "rag_model_id": rag_model_id,
            "tenant_id": remote.get("tenant_id"),
            "name": body.name,
            "avatar": remote.get("avatar") if _is_blank(body.avatar) else body.avatar,
            "description": body.description,
            "embedding_model": remote.get("embedding_model"),
            "permission": remote.get("permission"),
            "chunk_method": remote.get("chunk_method"),
            "parser_config": json.dumps(
                remote.get("parser_config"), ensure_ascii=False, separators=(",", ":")
            )
            if remote.get("parser_config") is not None
            else None,
            "chunk_count": remote.get("chunk_count") or 0,
            "document_count": remote.get("document_count") or 0,
            "token_num": remote.get("token_num") or 0,
            "status": 1,
            "creator": user.id,
            "updater": user.id,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        try:
            await self.repository.insert_dataset(values)
            await self.repository.session.commit()
        except Exception as exc:
            await self.repository.session.rollback()
            try:
                await client.delete_datasets([dataset_id])
            except AppError:
                pass
            if isinstance(exc, AppError):
                raise
            raise AppError(10167, params=(f"创建知识库失败: {exc}",)) from exc
        return dataset_dto(values)

    async def update(
        self, identifier: str, body: KnowledgeBaseBody, user: AuthUser
    ) -> dict[str, Any]:
        existing = await self.get_owned(identifier, user)
        if not _is_blank(body.name) and await self.repository.duplicate_dataset_name(
            user.id, str(body.name), str(existing["id"])
        ):
            raise AppError(10170)
        if not _is_blank(identifier) and await self.repository.dataset_id_conflict(
            identifier, str(existing["id"])
        ):
            raise AppError(10002)
        rag_model_id = body.rag_model_id
        effective_permission = body.permission
        effective_chunk_method = body.chunk_method
        if existing.get("dataset_id") and not _is_blank(rag_model_id):
            if _is_blank(effective_permission):
                effective_permission = existing.get("permission")
            if _is_blank(effective_chunk_method):
                effective_chunk_method = existing.get("chunk_method")
            client = await self._client(str(rag_model_id))
            remote_body = {
                "name": f"{user.username}_{body.name}" if not _is_blank(body.name) else None,
                "avatar": body.avatar,
                "description": body.description,
                "embedding_model": body.embedding_model,
                "permission": effective_permission,
                "chunk_method": effective_chunk_method,
                "parser_config": _json_object(body.parser_config),
            }
            await client.update_dataset(str(existing["dataset_id"]), remote_body)
        now = shanghai_now_naive()
        updater = body.updater if body.updater is not None else user.id
        updated_at = body.updated_at or now
        values = {
            "id": existing["id"],
            # The controller injects the literal path value into datasetId,
            # even when a legacy row was found through its local primary key.
            "dataset_id": identifier,
            "rag_model_id": rag_model_id,
            "name": body.name,
            "avatar": body.avatar,
            "description": body.description,
            "embedding_model": body.embedding_model,
            "permission": effective_permission,
            "chunk_method": effective_chunk_method,
            "parser_config": body.parser_config,
            "chunk_count": body.chunk_count,
            "token_num": body.token_num,
            "status": body.status,
            "creator": body.creator,
            "created_at": body.created_at,
            "updater": updater,
            "updated_at": updated_at,
        }
        try:
            await self.repository.update_dataset(values)
            # Java performs cache eviction inside the database transaction;
            # an eviction failure therefore rolls this update back.
            await get_redis().delete(f"knowledge:base:{existing['id']}")
            await self.repository.session.commit()
        except Exception:
            await self.repository.session.rollback()
            raise
        # BeanUtils copies request nulls onto the in-memory entity before
        # MyBatis' NOT_NULL update strategy preserves the stored columns.  The
        # Java response is built from that in-memory entity, so its null fields
        # intentionally differ from a subsequent GET of the row.
        return dataset_dto(values)

    async def delete(self, identifier: str, user: AuthUser, language: str | None = None) -> None:
        row = await self.get_owned(identifier, user)
        documents = await self.repository.all_documents(str(row["dataset_id"]))
        if documents:
            # Java's document orchestration necessarily resolves the adapter
            # when child records exist.
            client = await self._client(str(row.get("rag_model_id") or ""))
            ids = [str(item["document_id"]) for item in documents]
            if any(item.get("run") == "RUNNING" for item in documents):
                raise AppError(10199)
            try:
                await client.delete_documents(str(row["dataset_id"]), ids)
            except Exception as exc:
                raise _document_delete_error(exc, language) from exc
            await self.repository.delete_document_shadows(str(row["dataset_id"]), ids)
            await self.repository.update_stats(
                str(row["dataset_id"]),
                -len(ids),
                -sum(int(item.get("chunk_count") or 0) for item in documents),
                -sum(int(item.get("token_count") or 0) for item in documents),
            )
            # deleteDocuments is NOT_SUPPORTED in Java and its shadow cleanup
            # commits before the outer dataset transaction continues.
            await self.repository.session.commit()
            await _delete_cache_ignoring_errors(f"knowledge:base:{row['dataset_id']}")
        if not _is_blank(row.get("rag_model_id")) and not _is_blank(row.get("dataset_id")):
            client = await self._client(str(row["rag_model_id"]))
            await client.delete_datasets([str(row["dataset_id"])])
        await self.repository.delete_dataset_local(row)
        try:
            await get_redis().delete(f"knowledge:base:{row['id']}")
            await self.repository.session.commit()
        except Exception:
            await self.repository.session.rollback()
            raise

    async def batch_delete(
        self, identifiers: list[str], user: AuthUser, language: str | None = None
    ) -> None:
        rows = await self.repository.datasets_by_ids(identifiers)
        for row in rows:
            if row.get("creator") is None or int(row["creator"]) != user.id:
                raise AppError(10169)
        # Preserve Java's sequential external calls and stop-on-first-error semantics.
        for row in rows:
            await self.delete(str(row["dataset_id"]), user, language)

    async def rag_models(self) -> list[dict[str, Any]]:
        rows = await self.repository.rag_models()
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "id": row.get("id"),
                    "modelType": None,
                    "modelCode": None,
                    "modelName": row.get("model_name"),
                    "isDefault": None,
                    "isEnabled": None,
                    # ModelConfigEntity.configJson is a JSONObject.  Jackson
                    # preserves its dynamic snake_case keys instead of applying
                    # the DTO property naming strategy recursively.
                    "configJson": preserve_java_map_keys(_json_object(row.get("config_json"))),
                    "docLink": None,
                    "remark": None,
                    "sort": None,
                    "updater": None,
                    "updateDate": None,
                    "creator": None,
                    "createDate": None,
                }
            )
        return result

    async def _client(self, model_id: str) -> RAGFlowClient:
        config = await self.repository.rag_config(model_id)
        adapter_type = config.get("type")
        if adapter_type != "ragflow":
            raise AppError(10184, params=(f"适配器类型未注册: {adapter_type}",))
        try:
            return RAGFlowClient(config)
        except AppError as exc:
            # KnowledgeBaseAdapterFactory wraps adapter initialization and
            # validateConfig failures as RAG_ADAPTER_CREATION_FAILED.
            if exc.code in {10171, 10172, 10173, 10174}:
                raise AppError(10186) from exc
            raise


class KnowledgeDocumentService:
    def __init__(self, repository: KnowledgeRepository):
        self.repository = repository
        self.datasets = KnowledgeBaseService(repository)

    async def page(
        self,
        dataset_id: str,
        user: AuthUser,
        *,
        name: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        await self.datasets.get_owned(dataset_id, user)
        try:
            await self.reconcile(dataset_id, creator=user.id)
        except Exception:
            await self.repository.session.rollback()
        rows, total = await self.repository.documents_page(
            dataset_id,
            name=name,
            status=status,
            offset=(max(page, 1) - 1) * page_size,
            limit=page_size,
        )
        return {"total": total, "list": [document_dto(row) for row in rows]}

    async def upload(
        self,
        dataset_id: str,
        user: AuthUser,
        file: UploadFile,
        *,
        name: str | None,
        meta_fields: dict[str, Any] | None,
        chunk_method: str | None,
        parser_config: dict[str, Any] | None,
    ) -> dict[str, Any]:
        await self.datasets.get_owned(dataset_id, user)
        content = await file.read()
        if not dataset_id.strip() or not content:
            raise AppError(10003)
        file_name = file.filename if _is_blank(name) else name
        if _is_blank(file_name):
            raise AppError(10179)
        assert file_name is not None
        client = await self._client_for_dataset(dataset_id)
        remote = await client.upload_document(
            dataset_id,
            file,
            content,
            name=file_name,
            meta_fields=meta_fields,
            chunk_method=chunk_method,
            parser_config=parser_config,
        )
        if not remote.get("id"):
            raise AppError(10167, params=("远程上传成功但未返回有效 DocumentID",))
        remote.setdefault("dataset_id", dataset_id)
        shadow = dict(remote)
        if _is_blank(str(shadow.get("name")) if shadow.get("name") is not None else None):
            shadow["name"] = file_name
        # Java stores the original controller values in the shadow row, even
        # when invalid chunk methods were omitted from the RAGFlow request.
        shadow["chunk_method"] = chunk_method
        shadow["parser_config"] = parser_config
        inserted = await self.repository.upsert_document(dataset_id, shadow, creator=user.id)
        if inserted:
            await self.repository.update_stats(dataset_id, 1, 0, 0)
        await self.repository.session.commit()
        return remote_document_dto(remote, dataset_id)

    async def delete(
        self,
        dataset_id: str,
        ids: list[str] | None,
        user: AuthUser,
        language: str | None = None,
    ) -> None:
        await self.datasets.get_owned(dataset_id, user)
        if not ids:
            raise AppError(10178)
        rows = await self.repository.documents_by_remote_ids(dataset_id, ids)
        if len(rows) != len(ids):
            raise AppError(10169)
        if any(row.get("run") == "RUNNING" for row in rows):
            raise AppError(10199)
        chunks = sum(int(row.get("chunk_count") or 0) for row in rows)
        tokens = sum(int(row.get("token_count") or 0) for row in rows)
        client = await self._client_for_dataset(dataset_id)
        try:
            await client.delete_documents(dataset_id, ids)
        except Exception as exc:
            raise _document_delete_error(exc, language) from exc
        deleted = await self.repository.delete_document_shadows(dataset_id, ids)
        if deleted:
            await self.repository.update_stats(dataset_id, -len(ids), -chunks, -tokens)
        await self.repository.session.commit()
        await _delete_cache_ignoring_errors(f"knowledge:base:{dataset_id}")

    async def parse(self, dataset_id: str, ids: list[str], user: AuthUser) -> bool:
        await self.datasets.get_owned(dataset_id, user)
        if not ids:
            raise AppError(10178)
        client = await self._client_for_dataset(dataset_id)
        await client.parse_documents(dataset_id, ids)
        await self.repository.mark_documents_running(dataset_id, ids, shanghai_now_naive())
        await self.repository.session.commit()
        return True

    async def chunks(
        self,
        dataset_id: str,
        document_id: str,
        user: AuthUser,
        *,
        page: int,
        page_size: int,
        keywords: str | None,
        chunk_id: str | None,
    ) -> dict[str, Any]:
        await self.datasets.get_owned(dataset_id, user)
        client = await self._client_for_dataset(dataset_id)
        return await client.chunks(
            dataset_id,
            document_id,
            {"page": page, "page_size": page_size, "keywords": keywords, "id": chunk_id},
        )

    async def retrieval(self, dataset_id: str, body: RetrievalBody, user: AuthUser) -> dict[str, Any]:
        await self.datasets.get_owned(dataset_id, user)
        dataset_ids = body.dataset_ids or [dataset_id]
        if not dataset_ids:
            raise AppError(500, "未指定召回测试的知识库")
        page = body.page if body.page is not None and body.page >= 1 else 1
        page_size = body.page_size if body.page_size is not None and body.page_size >= 1 else 100
        top_k = body.top_k if body.top_k is None or body.top_k >= 1 else 1024
        threshold = body.similarity_threshold
        if threshold is not None:
            threshold = 0.2 if threshold < 0 else min(threshold, 1.0)
        payload: dict[str, Any] = {
            "dataset_ids": dataset_ids,
            "document_ids": body.document_ids,
            "question": body.question,
            "page": page,
            "page_size": page_size,
            "similarity_threshold": threshold,
            "vector_similarity_weight": body.vector_similarity_weight,
            "top_k": top_k,
            "rerank_id": body.rerank_id,
            "highlight": body.highlight,
            "keyword": body.keyword,
            "cross_languages": body.cross_languages,
            "metadata_condition": body.metadata_condition,
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        client = await self._client_for_dataset(dataset_ids[0])
        return await client.retrieval(payload)

    async def reconcile(self, dataset_id: str, *, creator: int | None = None) -> int:
        client = await self._client_for_dataset(dataset_id)
        remote: list[dict[str, Any]] = []
        page, total = 1, 2**63 - 1
        while (page - 1) * 100 < total:
            rows, total = await client.documents(dataset_id, page=page, page_size=100)
            if not rows:
                break
            remote.extend(rows)
            page += 1
        local = await self.repository.all_documents(dataset_id)
        remote_map = {str(item.get("id")): item for item in remote if item.get("id")}
        local_map = {str(item["document_id"]): item for item in local}
        new_count = 0
        for document_id, item in remote_map.items():
            prior = local_map.get(document_id)
            inserted = await self.repository.upsert_document(dataset_id, item, creator=creator)
            if inserted:
                new_count += 1
                await self.repository.update_stats(
                    dataset_id, 1, int(item.get("chunk_count") or 0), int(item.get("token_count") or 0)
                )
            elif prior:
                await self.repository.update_stats(
                    dataset_id,
                    0,
                    int(item.get("chunk_count") or 0) - int(prior.get("chunk_count") or 0),
                    int(item.get("token_count") or 0) - int(prior.get("token_count") or 0),
                )
        deleted_ids = [identifier for identifier in local_map if identifier not in remote_map]
        if deleted_ids:
            deleted_rows = [local_map[identifier] for identifier in deleted_ids]
            await self.repository.delete_document_shadows(dataset_id, deleted_ids)
            await self.repository.update_stats(
                dataset_id,
                -len(deleted_ids),
                -sum(int(row.get("chunk_count") or 0) for row in deleted_rows),
                -sum(int(row.get("token_count") or 0) for row in deleted_rows),
            )
        await self.repository.session.commit()
        return new_count

    async def sync_running(self) -> int:
        rows = await self.repository.running_documents()
        grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row["dataset_id"])].append(row)
        updates = 0
        for dataset_id, documents in grouped.items():
            try:
                client = await self._client_for_dataset(dataset_id)
            except Exception:
                await self.repository.session.rollback()
                continue
            for local in documents:
                try:
                    remote, _ = await client.documents(
                        dataset_id, page=1, page_size=1, document_id=str(local["document_id"])
                    )
                    if not remote:
                        await self.repository.mark_document_remote_deleted(
                            str(local["document_id"]), shanghai_now_naive()
                        )
                        await self.repository.session.commit()
                        updates += 1
                        continue
                    remote_status = remote[0].get("status")
                    remote_run = remote[0].get("run")
                    status_changed = remote_status is not None and str(remote_status) != str(local.get("status"))
                    run_changed = remote_run is not None and str(remote_run) != str(local.get("run"))
                    is_processing = remote_run in {"RUNNING", "UNSTART"}
                    if not (status_changed or run_changed or is_processing):
                        await self.repository.session.commit()
                        continue
                    before_tokens = int(local.get("token_count") or 0)
                    await self.repository.sync_running_document(
                        dataset_id,
                        str(local["document_id"]),
                        remote[0],
                        shanghai_now_naive(),
                    )
                    delta = int(remote[0].get("token_count") or 0) - before_tokens
                    if delta:
                        await self.repository.update_stats(dataset_id, 0, 0, delta)
                    await self.repository.session.commit()
                    updates += 1
                except Exception:
                    await self.repository.session.rollback()
                    continue
        return updates

    async def _client_for_dataset(self, dataset_id: str) -> RAGFlowClient:
        row = await self.repository.get_dataset(dataset_id)
        if row is None or not row.get("rag_model_id"):
            raise AppError(10164)
        return await self.datasets._client(str(row["rag_model_id"]))


def _document_delete_error(exc: Exception, language: str | None) -> AppError:
    """Match `new RenException(e.getMessage())` in the Java delete flow."""
    if isinstance(exc, AppError):
        message = exc.message or message_for(exc.code, language, *exc.params)
    else:
        message = str(exc)
    return AppError(500, message)


async def _delete_cache_ignoring_errors(key: str) -> None:
    try:
        await get_redis().delete(key)
    except Exception:
        # The Java document cleanup and remote-missing cleanup explicitly log
        # and continue when Redis is unavailable.
        return
