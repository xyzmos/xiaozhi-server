from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


class JavaModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
        str_strip_whitespace=False,
        serialize_by_alias=True,
    )


class PageData(JavaModel, Generic[T]):
    total: int
    list: list[T]


class PageQuery(JavaModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=10, ge=1)
    order_field: str | list[str] | None = None
    order: str | None = None


class DeleteIds(JavaModel):
    ids: list[str]


def page_payload(rows: list[Any], total: int) -> dict[str, Any]:
    return {"total": int(total), "list": rows}


def safe_order_by(
    requested: str | list[str] | None,
    *,
    allowed: set[str],
    default: str,
    transform: Callable[[str], str] | None = None,
) -> list[str]:
    fields = [requested] if isinstance(requested, str) else list(requested or [])
    selected = [field for field in fields if field in allowed]
    if not selected:
        selected = [default]
    return [transform(field) if transform else field for field in selected]
