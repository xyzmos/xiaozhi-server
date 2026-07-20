from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from fastapi import UploadFile

from app.core.errors import AppError

_DOCUMENT_CHUNK_METHODS = {
    "naive",
    "manual",
    "qa",
    "table",
    "paper",
    "book",
    "laws",
    "presentation",
    "picture",
    "one",
    "knowledge_graph",
    "email",
}
_RUN_STATUSES = {"UNSTART", "RUNNING", "CANCEL", "DONE", "FAIL"}
_DOCUMENT_PARSER_FIELDS = (
    "chunk_token_num",
    "delimiter",
    "layout_recognize",
    "html4excel",
    "auto_keywords",
    "auto_questions",
    "topn_tags",
    "raptor",
    "graphrag",
)
_DATASET_PARSER_FIELDS = (
    "chunk_token_num",
    "delimiter",
    "layout_recognize",
    "html4excel",
    "auto_keywords",
    "auto_questions",
)


class RAGFlowClient:
    """Async equivalent of the Java RAGFlow adapter and its wire contract."""

    def __init__(self, config: Mapping[str, Any]):
        self.config = dict(config)
        self.base_url = str(config.get("base_url") or config.get("baseUrl") or "").rstrip("/")
        self.api_key = str(config.get("api_key") or config.get("apiKey") or "")
        raw_timeout = config.get("timeout")
        if raw_timeout is None:
            self.timeout = 30.0
        else:
            try:
                self.timeout = float(int(str(raw_timeout)))
            except (TypeError, ValueError):
                self.timeout = 30.0
        self._validate(config)

    def _validate(self, config: Mapping[str, Any]) -> None:
        if not config:
            raise AppError(10164)
        if not self.base_url.strip():
            raise AppError(10171)
        if not self.api_key.strip():
            raise AppError(10172)
        if "你" in self.api_key:
            raise AppError(10173)
        if not self.base_url.startswith(("http://", "https://")):
            raise AppError(10174)
        adapter_type = "ragflow" if "type" not in config else str(config.get("type"))
        if adapter_type != "ragflow":
            raise AppError(10184, params=(f"适配器类型未注册: {adapter_type}",))

    async def request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        files: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if files is None:
            headers["Content-Type"] = "application/json"
            headers["Accept-Charset"] = "utf-8"
        normalized_params = {
            key: self._query_value(value) for key, value in (params or {}).items() if value is not None
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method,
                    self.base_url + endpoint,
                    params=normalized_params,
                    json=json_body,
                    files=files,
                    data=data,
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError(10167, params=(f"Request Failed: {exc}",)) from exc
        if not isinstance(payload, dict):
            raise AppError(10167, params=("Invalid Response",))
        code = payload.get("code")
        if code is not None:
            if isinstance(code, bool) or not isinstance(code, int):
                raise AppError(10167, params=("Request Failed: invalid response code type",))
            if code != 0:
                message = payload.get("message")
                if message is not None and not isinstance(message, str):
                    raise AppError(10167, params=("Request Failed: invalid response message type",))
                raise AppError(10167, params=(message or "Unknown RAGFlow Error",))
        return dict(payload)

    @staticmethod
    def _query_value(value: Any) -> Any:
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, list):
            # Java List.toString() is what the baseline URL builder sends.
            return "[" + ", ".join(str(item) for item in value) + "]"
        return value

    async def dataset_info(self, dataset_id: str) -> dict[str, Any] | None:
        payload = await self.request(
            "GET", "/api/v1/datasets", params={"id": dataset_id, "page": 1, "page_size": 1}
        )
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return _normalize_dataset_info(data[0])
        return None

    async def create_dataset(self, body: dict[str, Any]) -> dict[str, Any]:
        body = dict(body)
        body["permission"] = "me" if _blank(body.get("permission")) else body.get("permission")
        body["chunk_method"] = "naive" if _blank(body.get("chunk_method")) else body.get("chunk_method")
        if _blank(body.get("embedding_model")):
            configured_model = self.config.get("embedding_model", self.config.get("embeddingModel"))
            body["embedding_model"] = None if _blank(configured_model) else configured_model
        body["avatar"] = body.get("avatar") if not _blank(body.get("avatar")) else (
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        body["parser_config"] = _normalize_parser_config(
            body.get("parser_config"), fields=_DATASET_PARSER_FIELDS
        )
        payload = await self.request("POST", "/api/v1/datasets", json_body=body)
        data = payload.get("data")
        if not isinstance(data, dict) or not data.get("id"):
            raise AppError(10167, params=("Invalid response from createDataset: missing data object",))
        return _normalize_dataset_info(data)

    async def update_dataset(self, dataset_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
        body = dict(body)
        body["parser_config"] = _normalize_parser_config(
            body.get("parser_config"), fields=_DATASET_PARSER_FIELDS
        )
        payload = await self.request("PUT", f"/api/v1/datasets/{dataset_id}", json_body=body)
        return _normalize_dataset_info(payload["data"]) if isinstance(payload.get("data"), dict) else None

    async def delete_datasets(self, ids: list[str]) -> Any:
        return (await self.request("DELETE", "/api/v1/datasets", json_body={"ids": ids})).get("data")

    async def documents(
        self,
        dataset_id: str,
        *,
        page: int = 1,
        page_size: int = 10,
        name: str | None = None,
        status: str | None = None,
        document_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if name:
            params["name"] = name
        if status:
            status_number = int(status) if status.lstrip("-").isdigit() else None
            names = {0: "UNSTART", 1: "RUNNING", 2: "CANCEL", 3: "DONE", 4: "FAIL"}
            params["run"] = [names[status_number]] if status_number in names else []
        if document_id:
            params["id"] = document_id
        payload = await self.request("GET", f"/api/v1/datasets/{dataset_id}/documents", params=params)
        data = payload.get("data")
        if not isinstance(data, dict):
            return [], 0
        docs = data.get("docs")
        rows: list[dict[str, Any]] = []
        if isinstance(docs, list):
            for item in docs:
                if not isinstance(item, dict):
                    continue
                try:
                    rows.append(_normalize_upload_document(item))
                except AppError:
                    # The Java adapter skips an individual document whose
                    # strong DTO conversion fails and keeps the rest of page.
                    continue
        return rows, int(data.get("total") or 0)

    async def upload_document(
        self,
        dataset_id: str,
        file: UploadFile,
        content: bytes,
        *,
        name: str,
        meta_fields: dict[str, Any] | None,
        chunk_method: str | None,
        parser_config: dict[str, Any] | None,
    ) -> dict[str, Any]:
        import json

        form: dict[str, Any] = {"name": name}
        if meta_fields:
            form["meta"] = json.dumps(meta_fields, ensure_ascii=False, separators=(",", ":"))
        if not _blank(chunk_method):
            normalized_method = str(chunk_method).lower()
            if normalized_method in _DOCUMENT_CHUNK_METHODS:
                form["chunk_method"] = normalized_method
        normalized_parser = (
            _normalize_parser_config(
                parser_config,
                fields=_DOCUMENT_PARSER_FIELDS,
                validate_layout=True,
            )
            if parser_config
            else None
        )
        if normalized_parser is not None:
            form["parser_config"] = json.dumps(normalized_parser, ensure_ascii=False, separators=(",", ":"))
        payload = await self.request(
            "POST",
            f"/api/v1/datasets/{dataset_id}/documents",
            files={"file": (file.filename or name, content, file.content_type or "application/octet-stream")},
            data=form,
        )
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return _normalize_upload_document(data[0])
        if isinstance(data, dict):
            return _normalize_upload_document(data)
        raise AppError(10167, params=("远程上传成功但未返回有效 DocumentID",))

    async def delete_documents(self, dataset_id: str, ids: list[str]) -> None:
        await self.request(
            "DELETE", f"/api/v1/datasets/{dataset_id}/documents", json_body={"ids": ids}
        )

    async def parse_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        await self.request(
            "POST",
            f"/api/v1/datasets/{dataset_id}/chunks",
            json_body={"document_ids": document_ids},
        )

    async def chunks(
        self, dataset_id: str, document_id: str, params: Mapping[str, Any]
    ) -> dict[str, Any]:
        payload = await self.request(
            "GET", f"/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks", params=params
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            return {"chunks": [], "doc": None, "total": 0}
        try:
            return _normalize_chunk_list(data)
        except (TypeError, ValueError) as exc:
            raise AppError(10167, params=(str(exc),)) from exc

    async def retrieval(self, body: dict[str, Any]) -> dict[str, Any]:
        payload = await self.request("POST", "/api/v1/retrieval", json_body=body)
        data = payload.get("data")
        if not isinstance(data, dict):
            return {"chunks": [], "doc_aggs": [], "total": 0}
        try:
            return _normalize_retrieval_result(data)
        except (TypeError, ValueError) as exc:
            raise AppError(10167, params=(str(exc),)) from exc


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _normalize_parser_config(
    value: Any,
    *,
    fields: tuple[str, ...],
    validate_layout: bool = False,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("parser_config must be an object")
    result = {key: value.get(key) for key in fields}
    if validate_layout and result.get("layout_recognize") not in {None, "DeepDOC", "Simple"}:
        raise ValueError("invalid layout_recognize")
    if "raptor" in result and result["raptor"] is not None:
        nested = result["raptor"]
        if not isinstance(nested, Mapping):
            raise ValueError("raptor must be an object")
        result["raptor"] = {"use_raptor": nested.get("use_raptor")}
    if "graphrag" in result and result["graphrag"] is not None:
        nested = result["graphrag"]
        if not isinstance(nested, Mapping):
            raise ValueError("graphrag must be an object")
        result["graphrag"] = {"use_graphrag": nested.get("use_graphrag")}
    return result


def _normalize_upload_document(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    try:
        if result.get("parser_config") is not None:
            result["parser_config"] = _normalize_parser_config(
                result["parser_config"], fields=_DOCUMENT_PARSER_FIELDS, validate_layout=True
            )
    except (TypeError, ValueError) as exc:
        raise AppError(10167, params=("远程上传成功但未返回有效 DocumentID",)) from exc
    chunk_method = result.get("chunk_method")
    if chunk_method is not None:
        normalized_method = str(chunk_method).lower()
        if normalized_method not in _DOCUMENT_CHUNK_METHODS:
            raise AppError(10167, params=("远程上传成功但未返回有效 DocumentID",))
        result["chunk_method"] = normalized_method
    run = result.get("run")
    if run is not None and str(run) not in _RUN_STATUSES:
        raise AppError(10167, params=("远程上传成功但未返回有效 DocumentID",))
    return result


def _normalize_dataset_info(value: Mapping[str, Any]) -> dict[str, Any]:
    """Apply Jackson's DatasetDTO.InfoVO unknown-field and type boundary."""
    fields = (
        "id",
        "name",
        "avatar",
        "tenant_id",
        "description",
        "embedding_model",
        "permission",
        "chunk_method",
        "parser_config",
        "chunk_count",
        "document_count",
        "create_time",
        "update_time",
        "token_num",
        "create_date",
        "update_date",
    )
    try:
        result = {field: value.get(field) for field in fields}
        result["parser_config"] = _normalize_parser_config(
            result.get("parser_config"), fields=_DATASET_PARSER_FIELDS
        )
        for field in ("chunk_count", "document_count", "create_time", "update_time", "token_num"):
            raw_value = result[field]
            if raw_value is not None:
                result[field] = int(raw_value)
        return result
    except (TypeError, ValueError) as exc:
        raise AppError(10167, params=(str(exc),)) from exc


def _nullable_object(value: Any, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("response object has an invalid shape")
    return {field: value.get(field) for field in fields}


def _normalize_chunk_list(data: Mapping[str, Any]) -> dict[str, Any]:
    chunk_fields = (
        "id",
        "content",
        "document_id",
        "docnm_kwd",
        "important_keywords",
        "questions",
        "image_id",
        "dataset_id",
        "available",
        "positions",
        "token",
    )
    raw_chunks = data.get("chunks")
    if raw_chunks is None:
        chunks: list[dict[str, Any]] = []
    elif isinstance(raw_chunks, list):
        chunks = []
        for item in raw_chunks:
            normalized = _nullable_object(item, chunk_fields)
            if normalized is not None:
                chunks.append(normalized)
    else:
        raise TypeError("chunks must be an array")

    doc_fields = (
        "id",
        "thumbnail",
        "dataset_id",
        "chunk_method",
        "pipeline_id",
        "parser_config",
        "source_type",
        "type",
        "created_by",
        "name",
        "location",
        "size",
        "token_count",
        "chunk_count",
        "progress",
        "progress_msg",
        "process_begin_at",
        "process_duration",
        "meta_fields",
        "suffix",
        "run",
        "status",
        "create_time",
        "create_date",
        "update_time",
        "update_date",
    )
    doc = _nullable_object(data.get("doc"), doc_fields)
    if doc is not None:
        doc["parser_config"] = _normalize_parser_config(
            doc.get("parser_config"), fields=_DOCUMENT_PARSER_FIELDS, validate_layout=True
        )
        if doc.get("chunk_count") is not None:
            # DocumentDTO.InfoVO.chunkCount is Long, unlike the Integer field
            # on KnowledgeFilesDTO used by the document-list endpoint.
            doc["chunk_count"] = str(doc["chunk_count"])
        if doc.get("run") is not None and str(doc["run"]) not in _RUN_STATUSES:
            raise ValueError("invalid document run status")
    # ChunkDTO.ListVO.total is Long and therefore uses the Java global Long
    # serializer even for small values (including the adapter's default 0L).
    return {"chunks": chunks, "doc": doc, "total": str(int(data.get("total") or 0))}


def _normalize_retrieval_result(data: Mapping[str, Any]) -> dict[str, Any]:
    hit_fields = (
        "id",
        "content",
        "document_id",
        "dataset_id",
        "document_name",
        "document_keyword",
        "similarity",
        "vector_similarity",
        "term_similarity",
        "index",
        "highlight",
        "important_keywords",
        "questions",
        "image_id",
        "positions",
    )
    agg_fields = ("doc_name", "doc_id", "count")

    def normalize_list(raw: Any, fields: tuple[str, ...], name: str) -> list[dict[str, Any]]:
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise TypeError(f"{name} must be an array")
        values: list[dict[str, Any]] = []
        for item in raw:
            normalized = _nullable_object(item, fields)
            if normalized is not None:
                values.append(normalized)
        return values

    return {
        "chunks": normalize_list(data.get("chunks"), hit_fields, "chunks"),
        "doc_aggs": normalize_list(data.get("doc_aggs"), agg_fields, "doc_aggs"),
        # RetrievalDTO.ResultVO.total is also Long.
        "total": str(int(data.get("total") or 0)),
    }
