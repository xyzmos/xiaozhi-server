from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.responses import JavaJSONResponse, envelope, ok
from app.core.security import require_normal
from app.repositories.knowledge import KnowledgeRepository
from app.schemas.knowledge import DocumentBatchBody, KnowledgeBaseBody, RetrievalBody
from app.services.knowledge import KnowledgeBaseService, KnowledgeDocumentService, dataset_dto

knowledge_router = APIRouter()


def _base(session: AsyncSession) -> KnowledgeBaseService:
    return KnowledgeBaseService(KnowledgeRepository(session))


def _documents(session: AsyncSession) -> KnowledgeDocumentService:
    return KnowledgeDocumentService(KnowledgeRepository(session))


@knowledge_router.get("/datasets/rag-models")
async def rag_models(request: Request, session: AsyncSession = Depends(get_db)) -> JavaJSONResponse:
    require_normal(request)
    return ok(await _base(session).rag_models())


@knowledge_router.delete("/datasets/batch")
async def delete_datasets_batch(
    request: Request, ids: str = Query(), session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    user = require_normal(request)
    if not ids.strip():
        raise AppError(10003)
    await _base(session).batch_delete(
        ids.split(","), user, request.headers.get("Accept-Language")
    )
    return ok()


@knowledge_router.get("/datasets")
async def datasets_page(
    request: Request,
    name: str | None = None,
    page: int = 1,
    page_size: int = 10,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    return ok(
        await _base(session).page(
            require_normal(request),
            name,
            page,
            page_size,
            request.headers.get("Accept-Language"),
        )
    )


@knowledge_router.post("/datasets")
async def create_dataset(
    body: KnowledgeBaseBody, request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    return ok(await _base(session).create(body, require_normal(request)))


@knowledge_router.get("/datasets/{dataset_id}")
async def get_dataset(
    dataset_id: str, request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    return ok(dataset_dto(await _base(session).get_owned(dataset_id, require_normal(request))))


@knowledge_router.put("/datasets/{dataset_id}")
async def update_dataset(
    dataset_id: str,
    body: KnowledgeBaseBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    return ok(await _base(session).update(dataset_id, body, require_normal(request)))


@knowledge_router.delete("/datasets/{dataset_id}")
async def delete_dataset(
    dataset_id: str, request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    await _base(session).delete(
        dataset_id, require_normal(request), request.headers.get("Accept-Language")
    )
    return ok()


@knowledge_router.get("/datasets/{dataset_id}/documents/status/{status}")
async def documents_by_status(
    dataset_id: str,
    status: str,
    request: Request,
    page: int = 1,
    page_size: int = 10,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    return ok(
        await _documents(session).page(
            dataset_id,
            require_normal(request),
            name=None,
            status=status,
            page=page,
            page_size=page_size,
        )
    )


@knowledge_router.get("/datasets/{dataset_id}/documents")
async def documents_page(
    dataset_id: str,
    request: Request,
    name: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 10,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    return ok(
        await _documents(session).page(
            dataset_id,
            require_normal(request),
            name=name,
            status=status,
            page=page,
            page_size=page_size,
        )
    )


@knowledge_router.post("/datasets/{dataset_id}/documents")
async def upload_document(
    dataset_id: str,
    request: Request,
    file: Annotated[UploadFile, File()],
    name: Annotated[str | None, Form()] = None,
    chunk_method: Annotated[str | None, Form(alias="chunkMethod")] = None,
    meta_fields: Annotated[str | None, Form(alias="metaFields")] = None,
    parser_config: Annotated[str | None, Form(alias="parserConfig")] = None,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    return ok(
        await _documents(session).upload(
            dataset_id,
            require_normal(request),
            file,
            name=name,
            meta_fields=_parse_form_json(meta_fields),
            chunk_method=chunk_method,
            parser_config=_parse_form_json(parser_config),
        )
    )


@knowledge_router.delete("/datasets/{dataset_id}/documents")
async def delete_documents(
    dataset_id: str,
    body: DocumentBatchBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    await _documents(session).delete(
        dataset_id,
        body.ids,
        require_normal(request),
        request.headers.get("Accept-Language"),
    )
    return ok()


@knowledge_router.delete("/datasets/{dataset_id}/documents/{document_id}")
async def delete_document(
    dataset_id: str,
    document_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    await _documents(session).delete(
        dataset_id,
        [document_id],
        require_normal(request),
        request.headers.get("Accept-Language"),
    )
    return ok()


@knowledge_router.post("/datasets/{dataset_id}/chunks")
async def parse_documents(
    dataset_id: str,
    body: dict[str, Any],
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    user = require_normal(request)
    # Java validates dataset existence/ownership before it reads document_ids.
    # A missing dataset must therefore win over the controller's empty-body
    # business error.
    await _base(session).get_owned(dataset_id, user)
    document_ids = body.get("document_ids")
    if document_ids is not None and not isinstance(document_ids, list):
        # Spring fails Map<String,List<String>> deserialization before entering
        # the controller, which is handled as the generic code-500 envelope.
        raise RuntimeError("document_ids must be an array")
    if not document_ids:
        return JavaJSONResponse(envelope(None, code=500, msg="document_ids参数不能为空"))
    success = await _documents(session).parse(dataset_id, document_ids, user)
    return ok() if success else JavaJSONResponse(
        envelope(None, code=500, msg="文档解析失败，文档可能正在处理中")
    )


@knowledge_router.get("/datasets/{dataset_id}/documents/{document_id}/chunks")
async def list_chunks(
    dataset_id: str,
    document_id: str,
    request: Request,
    page: int = 1,
    page_size: int = 10,
    keywords: str | None = None,
    id: str | None = None,  # noqa: A002 - exact Java query parameter
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    return ok(
        await _documents(session).chunks(
            dataset_id,
            document_id,
            require_normal(request),
            page=page,
            page_size=page_size,
            keywords=keywords,
            chunk_id=id,
        )
    )


@knowledge_router.post("/datasets/{dataset_id}/retrieval-test")
async def retrieval_test(
    dataset_id: str,
    body: RetrievalBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    return ok(await _documents(session).retrieval(dataset_id, body, require_normal(request)))


def _parse_form_json(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"解析JSON字符串失败: {value}") from exc
    if not isinstance(result, dict):
        raise RuntimeError(f"解析JSON字符串失败: {value}")
    return dict(result)
