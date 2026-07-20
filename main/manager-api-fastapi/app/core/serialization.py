from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.core.config import get_settings

_SNAKE_PART = re.compile(r"_([a-zA-Z0-9])")
_LONG_FIELD_NAMES = {
    "id",
    "userId",
    "creator",
    "updater",
    "createUserId",
    "updateUserId",
    "createDateTimestamp",
    "createTime",
    "createTimeFrom",
    "createTimeTo",
    "fileSize",
    "lastConnectedAtTimestamp",
    "pid",
    "reportTime",
    "size",
    "timestamp",
    "tokenCount",
    "tokenNum",
    "totalDocCount",
    "totalTokenCount",
    "updateTime",
}


class JavaMap(dict[str, Any]):
    """Marker for Java ``Map`` payloads whose keys Jackson leaves untouched."""


def preserve_java_map_keys(value: Any) -> Any:
    """Recursively mark a dynamic Java Map/List graph as key-preserving."""

    if isinstance(value, Mapping):
        return JavaMap({str(key): preserve_java_map_keys(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [preserve_java_map_keys(item) for item in value]
    return value


def snake_to_camel(value: str) -> str:
    return _SNAKE_PART.sub(lambda match: match.group(1).upper(), value)


def _is_long_field(name: str | None) -> bool:
    if not name:
        return False
    return name in _LONG_FIELD_NAMES or name.endswith("Id") or name.endswith("Ids")


def java_compatible(value: Any, *, field_name: str | None = None) -> Any:
    if value is None or isinstance(value, str | bool | float):
        return value
    if isinstance(value, BaseModel):
        return java_compatible(value.model_dump(by_alias=True, exclude_unset=False), field_name=field_name)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return java_compatible(dataclasses.asdict(value), field_name=field_name)
    if isinstance(value, Enum):
        return java_compatible(value.value, field_name=field_name)
    if isinstance(value, datetime):
        timezone = ZoneInfo(get_settings().timezone)
        localized = value.astimezone(timezone) if value.tzinfo else value
        return localized.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int):
        return str(value) if _is_long_field(field_name) or not -(2**31) <= value < 2**31 else value
    if isinstance(value, bytes):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, JavaMap):
        return {
            str(raw_key): java_compatible(item, field_name=snake_to_camel(str(raw_key)))
            for raw_key, item in value.items()
        }
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = snake_to_camel(str(raw_key))
            result[key] = java_compatible(item, field_name=key)
        return result
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [java_compatible(item, field_name=field_name) for item in value]
    return value
