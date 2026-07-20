from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse

app = FastAPI(title="manager-api repeatable external-service mock")

_requests: list[dict[str, Any]] = []
_datasets: dict[str, dict[str, Any]] = {}
_documents: dict[str, dict[str, Any]] = {}


async def _capture(request: Request, body: Any = None) -> None:
    _requests.append(
        {
            "method": request.method,
            "path": request.url.path,
            "query": dict(request.query_params),
            "headers": {
                key.lower(): value
                for key, value in request.headers.items()
                if key.lower() in {"authorization", "content-type"}
            },
            "body": body,
        }
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "UP"}


@app.get("/__requests")
async def requests() -> dict[str, Any]:
    return {"requests": list(_requests)}


@app.delete("/__requests")
async def reset_requests() -> dict[str, bool]:
    _requests.clear()
    return {"reset": True}


@app.post("/api/commands/{client_id}")
async def mqtt_command(client_id: str, request: Request) -> JSONResponse:
    body = await request.json()
    await _capture(request, body)
    method = body.get("payload", {}).get("method") if isinstance(body, Mapping) else None
    if method == "tools/list":
        response = {
            "success": True,
            "data": {
                "tools": [
                    {
                        "name": "contract.echo",
                        "description": "repeatable contract fixture",
                        "inputSchema": {"type": "object"},
                    }
                ]
            },
        }
    elif method == "tools/call":
        response = {"success": True, "data": {"content": [{"type": "text", "text": '{"echo":true}'}]}}
    else:
        response = {"success": True, "data": {"clientId": client_id}}
    return JSONResponse(response)


@app.post("/api/devices/status")
async def mqtt_status(request: Request) -> JSONResponse:
    body = await request.json()
    await _capture(request, body)
    client_ids = body.get("clientIds", []) if isinstance(body, Mapping) else []
    return JSONResponse({"success": True, "data": {str(value): True for value in client_ids}})


@app.post("/api/call/{operation}")
async def mqtt_call(operation: str, request: Request) -> JSONResponse:
    body = await request.json()
    await _capture(request, body)
    return JSONResponse({"status": "success", "message": operation})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    body = await request.json()
    await _capture(request, body)
    return JSONResponse(
        {
            "id": "chatcmpl-contract",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "contract summary"}}],
        }
    )


@app.get("/api/v1/datasets")
async def list_datasets(request: Request) -> JSONResponse:
    await _capture(request)
    dataset_id = request.query_params.get("id")
    values = list(_datasets.values())
    if dataset_id:
        values = [value for value in values if value["id"] == dataset_id]
    return JSONResponse({"code": 0, "data": values})


@app.post("/api/v1/datasets")
async def create_dataset(request: Request) -> JSONResponse:
    body = await request.json()
    await _capture(request, body)
    identifier = "rag-contract-" + hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:12]
    value = {
        "id": identifier,
        "name": body.get("name"),
        "description": body.get("description"),
        "tenant_id": "tenant-contract",
        "avatar": body.get("avatar"),
        "document_count": 0,
        "chunk_count": 0,
        "token_num": 0,
    }
    _datasets[identifier] = value
    return JSONResponse({"code": 0, "data": value})


@app.put("/api/v1/datasets/{dataset_id}")
async def update_dataset(dataset_id: str, request: Request) -> JSONResponse:
    body = await request.json()
    await _capture(request, body)
    value = _datasets.setdefault(dataset_id, {"id": dataset_id})
    value.update(body)
    return JSONResponse({"code": 0, "data": value})


@app.delete("/api/v1/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str, request: Request) -> JSONResponse:
    await _capture(request)
    _datasets.pop(dataset_id, None)
    return JSONResponse({"code": 0, "data": True})


@app.post("/api/v1/datasets/{dataset_id}/documents")
async def upload_document(
    dataset_id: str,
    request: Request,
    file: Annotated[UploadFile, File()],
) -> JSONResponse:
    content = await file.read()
    body: dict[str, Any] = {
        "filename": file.filename,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    await _capture(request, body)
    identifier = "doc-contract-" + str(body["sha256"])[:12]
    value = {
        "id": identifier,
        "dataset_id": dataset_id,
        "name": file.filename,
        "size": len(content),
        "run": "UNSTART",
        "progress": 0.0,
        "chunk_count": 0,
        "token_count": 0,
    }
    _documents[identifier] = value
    return JSONResponse({"code": 0, "data": [value]})


@app.get("/api/v1/datasets/{dataset_id}/documents")
async def list_documents(dataset_id: str, request: Request) -> JSONResponse:
    await _capture(request)
    document_id = request.query_params.get("id")
    values = [value for value in _documents.values() if value["dataset_id"] == dataset_id]
    if document_id:
        values = [value for value in values if value["id"] == document_id]
    return JSONResponse({"code": 0, "data": {"docs": values, "total": len(values)}})


@app.post("/api/v1/datasets/{dataset_id}/chunks")
async def parse_documents(dataset_id: str, request: Request) -> JSONResponse:
    body = await request.json()
    await _capture(request, body)
    for document_id in body.get("document_ids", []):
        if document_id in _documents:
            _documents[document_id].update(run="DONE", progress=1.0, chunk_count=2, token_count=17)
    return JSONResponse({"code": 0, "data": True})


@app.delete("/api/v1/datasets/{dataset_id}/documents")
async def delete_documents(dataset_id: str, request: Request) -> JSONResponse:
    body = await request.json()
    await _capture(request, body)
    for document_id in body.get("ids", body.get("document_ids", [])):
        _documents.pop(document_id, None)
    return JSONResponse({"code": 0, "data": True})


@app.post("/voice-clone")
async def clone_voice(request: Request) -> JSONResponse:
    content = await request.body()
    await _capture(request, {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    return JSONResponse({"voice_id": "voice-contract", "status": "success"})


@app.post("/transient/{failures}")
async def transient(failures: int, request: Request) -> JSONResponse:
    await _capture(request)
    count = sum(1 for item in _requests if item["path"] == request.url.path)
    if count <= failures:
        await asyncio.sleep(0)
        return JSONResponse({"error": "retryable"}, status_code=503)
    return JSONResponse({"ok": True})


@app.get("/binary")
async def binary(request: Request) -> JSONResponse:
    await _capture(request)
    content = b"contract-binary\x00\xff"
    return JSONResponse({"base64": base64.b64encode(content).decode(), "size": len(content)})
