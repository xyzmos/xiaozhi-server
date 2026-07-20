from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import AliasChoices, Field

from app.schemas.common import JavaModel


class KnowledgeBaseBody(JavaModel):
    id: str | None = None
    dataset_id: str | None = None
    rag_model_id: str | None = None
    name: str | None = None
    avatar: str | None = None
    description: str | None = None
    embedding_model: str | None = None
    permission: str | None = None
    chunk_method: str | None = None
    parser_config: str | None = None
    chunk_count: int | None = None
    token_num: int | None = None
    status: int | None = None
    creator: int | None = None
    created_at: datetime | None = None
    updater: int | None = None
    updated_at: datetime | None = None
    document_count: int | None = None
    error_message: str | None = None


class DocumentBatchBody(JavaModel):
    ids: list[str] | None = Field(
        default=None,
        validation_alias=AliasChoices("ids", "document_ids"),
    )


class RetrievalBody(JavaModel):
    dataset_ids: list[str] | None = None
    document_ids: list[str] | None = None
    question: str | None = None
    page: int | None = None
    page_size: int | None = None
    similarity_threshold: float | None = None
    vector_similarity_weight: float | None = None
    top_k: int | None = None
    rerank_id: str | None = None
    highlight: bool | None = None
    keyword: bool | None = None
    cross_languages: list[str] | None = None
    metadata_condition: dict[str, Any] | None = None
