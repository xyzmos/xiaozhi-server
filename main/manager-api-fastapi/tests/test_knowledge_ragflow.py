from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from sqlalchemy import text
from starlette.datastructures import Headers, UploadFile
from starlette.requests import Request

from app.core.errors import AppError
from app.core.responses import ok
from app.core.security import AuthUser
from app.integrations.ragflow import RAGFlowClient
from app.repositories.knowledge import KnowledgeRepository
from app.routers.knowledge import parse_documents
from app.schemas.knowledge import DocumentBatchBody, KnowledgeBaseBody, RetrievalBody
from app.services.knowledge import (
    KnowledgeBaseService,
    KnowledgeDocumentService,
    _document_delete_error,
    dataset_dto,
)
from tests.domain_support import FakeRedis, sqlite_session

USER = AuthUser(id=7, username="alice", super_admin=0, status=1, token=str(7), row={})

KNOWLEDGE_SCHEMA = [
    "CREATE TABLE ai_rag_dataset (id TEXT PRIMARY KEY,dataset_id TEXT,rag_model_id TEXT,tenant_id TEXT,name TEXT,"
    "avatar TEXT,description TEXT,embedding_model TEXT,permission TEXT,chunk_method TEXT,parser_config TEXT,"
    "chunk_count INTEGER,document_count INTEGER,token_num INTEGER,status INTEGER,creator INTEGER,created_at DATETIME,"
    "updater INTEGER,updated_at DATETIME)",
]


def test_ragflow_configuration_timeout_and_adapter_validation() -> None:
    assert RAGFlowClient({"base_url": "https://rag.test", "api_key": "key"}).timeout == 30.0
    assert RAGFlowClient(
        {"base_url": "https://rag.test", "api_key": "key", "timeout": "invalid"}
    ).timeout == 30.0
    assert RAGFlowClient(
        {"base_url": "https://rag.test", "api_key": "key", "timeout": "11"}
    ).timeout == 11.0
    for config, code in (
        ({}, 10164),
        ({"api_key": "key"}, 10171),
        ({"base_url": "https://rag.test"}, 10172),
        ({"base_url": "rag.test", "api_key": "key"}, 10174),
        ({"type": "other", "base_url": "https://rag.test", "api_key": "key"}, 10184),
    ):
        with pytest.raises(AppError) as caught:
            RAGFlowClient(config)
        assert caught.value.code == code


@pytest.mark.asyncio
async def test_ragflow_json_wire_headers_query_and_error_mapping() -> None:
    client = RAGFlowClient({"base_url": "https://rag.test", "api_key": "secret"})
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get("https://rag.test/query").mock(
            return_value=httpx.Response(200, json={"code": 0, "data": {}})
        )
        await client.request("GET", "/query", params={"run": ["DONE", "FAIL"], "enabled": True})
        request = route.calls.last.request
        assert request.headers["Authorization"] == "Bearer secret"
        assert request.headers["Accept-Charset"] == "utf-8"
        assert request.url.params["run"] == "[DONE, FAIL]"
        assert request.url.params["enabled"] == "true"

    with respx.mock:
        respx.get("https://rag.test/fail").mock(
            return_value=httpx.Response(200, json={"code": 7, "message": "remote failed"})
        )
        with pytest.raises(AppError) as caught:
            await client.request("GET", "/fail")
        assert caught.value.code == 10167 and caught.value.params == ("remote failed",)

    with respx.mock:
        respx.get("https://rag.test/bad-code").mock(
            return_value=httpx.Response(200, json={"code": "0", "data": {}})
        )
        with pytest.raises(AppError) as caught:
            await client.request("GET", "/bad-code")
        assert caught.value.code == 10167


@pytest.mark.asyncio
async def test_ragflow_upload_filters_invalid_chunk_method_and_parser_fields() -> None:
    client = RAGFlowClient({"base_url": "https://rag.test", "api_key": "secret"})
    upload = UploadFile(
        io.BytesIO(b"hello"),
        filename="manual.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://rag.test/api/v1/datasets/dataset/documents").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": [{"id": "document", "name": "manual.txt", "run": "UNSTART"}],
                },
            )
        )
        result = await client.upload_document(
            "dataset",
            upload,
            b"hello",
            name="display.txt",
            meta_fields={"tag": "测试"},
            chunk_method="NOT-A-METHOD",
            parser_config={"chunk_token_num": 64, "extra": "drop"},
        )
        request = route.calls.last.request
        multipart = request.content

        assert result["id"] == "document"
        assert request.headers["Authorization"] == "Bearer secret"
        assert "Accept-Charset" not in request.headers
        assert b'name="chunk_method"' not in multipart
        assert b'"chunk_token_num":64' in multipart
        assert b'"delimiter":null' in multipart
        assert b'"extra"' not in multipart
        assert "测试".encode() in multipart


@pytest.mark.asyncio
async def test_ragflow_dataset_response_uses_strong_info_dto_shape() -> None:
    client = RAGFlowClient({"base_url": "https://rag.test", "api_key": "secret"})
    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://rag.test/api/v1/datasets").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "id": "dataset",
                        "name": "alice_FAQ",
                        "chunk_count": "2",
                        "parser_config": {"chunk_token_num": 64, "unknown": "drop"},
                        "unknown": "drop",
                    },
                },
            )
        )
        result = await client.create_dataset({"name": "alice_FAQ"})

    assert result["chunk_count"] == 2
    assert "unknown" not in result
    assert "unknown" not in result["parser_config"]
    assert result["parser_config"]["delimiter"] is None


@pytest.mark.asyncio
async def test_ragflow_strong_chunk_and_retrieval_response_shapes() -> None:
    client = RAGFlowClient({"base_url": "https://rag.test", "api_key": "secret"})
    with respx.mock(assert_all_called=True) as mock:
        mock.route(method="GET").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "chunks": [{"id": "chunk", "content": "text", "extra": "drop"}],
                        "doc": {
                            "id": "doc",
                            "chunk_count": 2147483648,
                            "parser_config": {"chunk_token_num": 128, "extra": "drop"},
                            "run": "DONE",
                            "extra": "drop",
                        },
                        "total": 1,
                        "extra": "drop",
                    },
                },
            )
        )
        chunks = await client.chunks("ds", "doc", {"page": 1, "page_size": 10})

        mock.post("https://rag.test/api/v1/retrieval").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "chunks": [{"id": "hit", "content": "answer", "extra": "drop"}],
                        "doc_aggs": [{"doc_name": "doc", "doc_id": "id", "count": 2, "extra": 1}],
                        "total": 1,
                        "meta_summary": {"total_tokens": 2147483648},
                    },
                },
            )
        )
        retrieval = await client.retrieval({"dataset_ids": ["ds"], "question": "q"})

    assert chunks["doc"]["chunk_count"] == "2147483648"
    assert chunks["total"] == "1"
    assert "extra" not in chunks["doc"] and "extra" not in chunks["chunks"][0]
    assert chunks["chunks"][0]["document_id"] is None
    assert chunks["doc"]["parser_config"]["delimiter"] is None
    assert set(retrieval) == {"chunks", "doc_aggs", "total"}
    assert retrieval["total"] == "1"
    assert "extra" not in retrieval["chunks"][0] and "extra" not in retrieval["doc_aggs"][0]
    assert retrieval["chunks"][0]["document_id"] is None


@pytest.mark.asyncio
async def test_retrieval_service_sends_snake_case_non_null_and_java_bounds() -> None:
    repository = SimpleNamespace()
    service = KnowledgeDocumentService(repository)  # type: ignore[arg-type]
    service.datasets.get_owned = AsyncMock(return_value={})  # type: ignore[method-assign]
    client = SimpleNamespace(retrieval=AsyncMock(return_value={"chunks": [], "doc_aggs": [], "total": 0}))
    service._client_for_dataset = AsyncMock(return_value=client)  # type: ignore[method-assign]

    await service.retrieval(
        "dataset",
        RetrievalBody(
            question="hello",
            page=0,
            page_size=0,
            top_k=0,
            similarity_threshold=-1,
            highlight=False,
            metadata_condition={"op": "and"},
        ),
        USER,
    )
    payload = client.retrieval.await_args.args[0]
    assert payload == {
        "dataset_ids": ["dataset"],
        "question": "hello",
        "page": 1,
        "page_size": 100,
        "similarity_threshold": 0.2,
        "top_k": 1024,
        "highlight": False,
        "metadata_condition": {"op": "and"},
    }


def test_knowledge_long_null_and_batch_alias_contract() -> None:
    dto = dataset_dto(
        {
            "id": "local",
            "chunk_count": 2147483648,
            "token_num": 2147483649,
            "document_count": 5,
        }
    )
    assert dto["chunkCount"] == "2147483648"
    assert dto["tokenNum"] == "2147483649"
    assert dto["documentCount"] is None
    assert DocumentBatchBody.model_validate({"document_ids": ["a"]}).ids == ["a"]
    assert DocumentBatchBody.model_validate({"ids": ["b"]}).ids == ["b"]
    assert DocumentBatchBody.model_validate({"documentIds": ["c"]}).ids is None
    body = KnowledgeBaseBody.model_validate(
        {
            "creator": "2147483648",
            "createdAt": "2026-07-20 10:00:00",
            "updater": "2147483649",
            "updatedAt": "2026-07-20 11:00:00",
            "documentCount": 2,
            "errorMessage": "error",
        }
    )
    assert body.creator == 2147483648 and body.updater == 2147483649
    assert body.created_at is not None and body.updated_at is not None
    assert body.document_count == 2 and body.error_message == "error"


@pytest.mark.asyncio
async def test_rag_model_config_keeps_java_jsonobject_snake_case_keys() -> None:
    repository = SimpleNamespace(
        rag_models=AsyncMock(
            return_value=[
                {
                    "id": "RAG_RAGFlow",
                    "model_name": "RAGFlow",
                    "config_json": '{"type":"ragflow","base_url":"http://localhost","api_key":"secret"}',
                }
            ]
        )
    )
    result = await KnowledgeBaseService(repository).rag_models()  # type: ignore[arg-type]
    payload = json.loads(ok(result).body)
    assert payload["data"][0]["configJson"] == {
        "type": "ragflow",
        "base_url": "http://localhost",
        "api_key": "secret",
    }


@pytest.mark.asyncio
async def test_parse_documents_checks_missing_dataset_before_empty_document_ids() -> None:
    async with sqlite_session(KNOWLEDGE_SCHEMA) as session:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/datasets/missing/chunks",
                "headers": [],
            }
        )
        request.state.user = USER
        with pytest.raises(AppError) as caught:
            await parse_documents("missing", {}, request, session)
    assert caught.value.code == 10163


@pytest.mark.asyncio
async def test_dataset_update_preserves_db_null_columns_but_returns_java_in_memory_nulls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    monkeypatch.setattr("app.services.knowledge.get_redis", lambda: redis)
    async with sqlite_session(KNOWLEDGE_SCHEMA) as session:
        await session.execute(
            text(
                "INSERT INTO ai_rag_dataset VALUES "
                "('local','remote','rag','tenant','FAQ','avatar','desc','embed','me','naive','{}',"
                "3,2,10,1,7,'2026-01-01 00:00:00',7,'2026-01-01 00:00:00')"
            )
        )
        await session.commit()

        result = await KnowledgeBaseService(KnowledgeRepository(session)).update(
            "remote", KnowledgeBaseBody(), USER
        )
        stored = (
            await session.execute(
                text(
                    "SELECT name,avatar,description,embedding_model,permission,chunk_method,creator,created_at "
                    "FROM ai_rag_dataset WHERE id='local'"
                )
            )
        ).one()

        assert tuple(stored[:7]) == ("FAQ", "avatar", "desc", "embed", "me", "naive", 7)
        assert stored.created_at is not None
        assert result["datasetId"] == "remote"
        assert result["name"] is None and result["permission"] is None
        assert result["creator"] is None and result["createdAt"] is None
        assert result["updater"] == USER.id and result["updatedAt"] is not None


@pytest.mark.asyncio
async def test_dataset_update_rejects_dataset_id_conflict_before_remote_call() -> None:
    repository = SimpleNamespace(
        get_dataset=AsyncMock(return_value={"id": "local", "creator": USER.id, "dataset_id": "old"}),
        duplicate_dataset_name=AsyncMock(return_value=False),
        dataset_id_conflict=AsyncMock(return_value=True),
    )
    service = KnowledgeBaseService(repository)  # type: ignore[arg-type]
    with pytest.raises(AppError) as caught:
        await service.update("conflicting", KnowledgeBaseBody(), USER)
    assert caught.value.code == 10002


@pytest.mark.asyncio
async def test_dataset_create_generic_db_failure_rolls_back_remote_and_maps_10167() -> None:
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    repository = SimpleNamespace(
        session=session,
        duplicate_dataset_name=AsyncMock(return_value=False),
        insert_dataset=AsyncMock(side_effect=RuntimeError("db failed")),
    )
    client = SimpleNamespace(
        create_dataset=AsyncMock(return_value={"id": "remote-id"}),
        delete_datasets=AsyncMock(return_value=None),
    )
    service = KnowledgeBaseService(repository)  # type: ignore[arg-type]
    service._client = AsyncMock(return_value=client)  # type: ignore[method-assign]
    with pytest.raises(AppError) as caught:
        await service.create(KnowledgeBaseBody(name="FAQ", rag_model_id="rag"), USER)

    assert caught.value.code == 10167
    assert caught.value.params == ("创建知识库失败: db failed",)
    session.rollback.assert_awaited_once()
    client.delete_datasets.assert_awaited_once_with(["remote-id"])


@pytest.mark.asyncio
async def test_running_document_missing_remotely_is_cancelled_idempotently() -> None:
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    repository = SimpleNamespace(
        session=session,
        running_documents=AsyncMock(
            return_value=[{"dataset_id": "ds", "document_id": "doc", "token_count": 3}]
        ),
        mark_document_remote_deleted=AsyncMock(return_value=1),
    )
    client = SimpleNamespace(documents=AsyncMock(return_value=([], 0)))
    service = KnowledgeDocumentService(repository)  # type: ignore[arg-type]
    service._client_for_dataset = AsyncMock(return_value=client)  # type: ignore[method-assign]

    assert await service.sync_running() == 1
    repository.mark_document_remote_deleted.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_running_sync_updates_only_java_status_columns_and_token_delta() -> None:
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    repository = SimpleNamespace(
        session=session,
        running_documents=AsyncMock(
            return_value=[
                {
                    "dataset_id": "ds",
                    "document_id": "doc",
                    "status": "1",
                    "run": "RUNNING",
                    "token_count": 3,
                }
            ]
        ),
        sync_running_document=AsyncMock(return_value=1),
        update_stats=AsyncMock(return_value=None),
    )
    remote = {
        "id": "doc",
        "status": "1",
        "run": "DONE",
        "token_count": 7,
        "name": "must-not-be-written-by-status-sync",
    }
    client = SimpleNamespace(documents=AsyncMock(return_value=([remote], 1)))
    service = KnowledgeDocumentService(repository)  # type: ignore[arg-type]
    service._client_for_dataset = AsyncMock(return_value=client)  # type: ignore[method-assign]

    assert await service.sync_running() == 1
    synced_remote = repository.sync_running_document.await_args.args[2]
    assert synced_remote is remote
    repository.update_stats.assert_awaited_once_with("ds", 0, 0, 4)
    session.commit.assert_awaited_once()


def test_document_delete_remote_error_is_wrapped_as_java_code_500() -> None:
    translated = _document_delete_error(AppError(10167, params=("remote failed",)), "en-US")
    plain = _document_delete_error(RuntimeError("network down"), None)
    assert translated.code == 500 and translated.message and "remote failed" in translated.message
    assert (plain.code, plain.message) == (500, "network down")
