from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from starlette.responses import JSONResponse, Response

from app.core.i18n import message_for
from app.core.serialization import java_compatible


class JavaJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(
            java_compatible(content),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")


def envelope(data: Any = None, *, code: int = 0, msg: str = "success") -> dict[str, Any]:
    return {"code": code, "msg": msg, "data": data}


def ok(data: Any = None) -> JavaJSONResponse:
    return JavaJSONResponse(envelope(data))


def error_response(
    request: Request,
    code: int,
    message: str | None = None,
    *,
    status_code: int = 200,
    params: tuple[object, ...] = (),
    media_type: str = "application/json",
) -> JavaJSONResponse:
    translated = message or message_for(code, request.headers.get("Accept-Language"), *params)
    return JavaJSONResponse(
        envelope(None, code=code, msg=translated),
        status_code=status_code,
        media_type=media_type,
    )


def raw_json(content: Any, *, exclude_none: bool = False, status_code: int = 200) -> Response:
    normalized = java_compatible(content)
    if exclude_none:
        normalized = _drop_none(normalized)
    body = json.dumps(normalized, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    return Response(
        body,
        status_code=status_code,
        media_type="application/json",
        headers={"Content-Length": str(len(body))},
    )


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _drop_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value
