from __future__ import annotations

from typing import Any

from app.schemas.common import JavaModel


class ModelConfigBody(JavaModel):
    id: str | None = None
    model_code: str | None = None
    model_name: str | None = None
    is_default: int | None = None
    is_enabled: int | None = None
    config_json: dict[str, Any] | None = None
    doc_link: str | None = None
    remark: str | None = None
    sort: int | None = None

class ModelProviderBody(JavaModel):
    id: str | None = None
    model_type: str | None = None
    provider_code: str | None = None
    name: str | None = None
    fields: str | None = None
    sort: int | None = None
