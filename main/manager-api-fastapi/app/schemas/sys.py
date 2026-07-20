from __future__ import annotations

from pydantic import field_validator

from app.schemas.common import JavaModel


def _not_blank(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("must not be blank")
    return value


class SysParamPayload(JavaModel):
    id: int | None = None
    param_code: str | None = None
    param_value: str | None = None
    value_type: str | None = None
    remark: str | None = None


class DictTypePayload(JavaModel):
    # Controller calls ValidatorUtils without the DTO's custom groups, so these constraints don't execute in Java.
    id: int | None = None
    dict_type: str | None = None
    dict_name: str | None = None
    remark: str | None = None
    sort: int | None = None


class DictDataPayload(JavaModel):
    # See DictTypePayload: Add/Update/DefaultGroup annotations are skipped by the Java controller.
    id: int | None = None
    dict_type_id: int | None = None
    dict_label: str | None = None
    dict_value: str | None = None
    remark: str | None = None
    sort: int | None = None


class EmitServerActionRequest(JavaModel):
    target_ws: str
    action: str | None

    _validate_target = field_validator("target_ws")(_not_blank)
