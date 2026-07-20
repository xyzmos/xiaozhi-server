from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

from redis.asyncio import Redis

from app.core.config import get_settings

_client: Redis | None = None
logger = logging.getLogger(__name__)


class JavaRedisCodec:
    """Wire-compatible subset of Spring Data's ``RedisSerializer.json()``.

    Spring enables Jackson default typing for non-final values.  Consequently a
    plain JSON map/list cannot be read by the retained Java rollback service.  A
    map carries ``@class`` and a collection uses Jackson's wrapper-array form.
    ``java_type`` and ``item_java_type`` cover the few caches whose Java readers
    cast values to concrete DTO/entity classes.
    """

    @staticmethod
    def encode(
        value: Any,
        *,
        java_type: str | None = None,
        item_java_type: str | None = None,
        field_java_types: dict[str, str] | None = None,
    ) -> bytes:
        wire = JavaRedisCodec._encode_value(
            value,
            java_type=java_type,
            item_java_type=item_java_type,
            field_java_types=field_java_types,
            nested=False,
        )
        return json.dumps(wire, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def decode(value: bytes | str | None) -> Any:
        if value is None:
            return None
        raw = value.decode("utf-8") if isinstance(value, bytes) else value
        try:
            return JavaRedisCodec._decode_value(json.loads(raw))
        except json.JSONDecodeError:
            return raw

    @staticmethod
    def _encode_value(
        value: Any,
        *,
        java_type: str | None = None,
        item_java_type: str | None = None,
        field_java_types: dict[str, str] | None = None,
        nested: bool = True,
    ) -> Any:
        if value is None or isinstance(value, str | bool | float):
            return value
        if isinstance(value, int):
            # Jackson's default typing only adds the Long wrapper when the
            # runtime value sits behind an Object-typed container slot.  A
            # top-level Long, or a field with a declared Long type, is emitted
            # as an ordinary JSON number.
            if not nested or java_type == "java.lang.Long" or -(2**31) <= value < 2**31:
                return value
            return ["java.lang.Long", value]
        if isinstance(value, datetime):
            timezone = ZoneInfo(get_settings().timezone)
            localized = value.replace(tzinfo=timezone) if value.tzinfo is None else value.astimezone(timezone)
            return ["java.util.Date", int(localized.timestamp() * 1000)]
        if isinstance(value, dict):
            selected_type = java_type or "java.util.HashMap"
            result: dict[str, Any] = {"@class": selected_type}
            pojo = selected_type not in {
                "java.util.HashMap",
                "java.util.LinkedHashMap",
                "java.util.TreeMap",
                "cn.hutool.json.JSONObject",
            }
            for raw_key, item in value.items():
                if raw_key == "@class":
                    continue
                key = _snake_to_camel(str(raw_key)) if pojo else str(raw_key)
                child_type = (field_java_types or {}).get(key) or (field_java_types or {}).get(str(raw_key))
                result[key] = JavaRedisCodec._encode_value(item, java_type=child_type, nested=True)
            return result
        if isinstance(value, set | frozenset):
            return [
                "java.util.HashSet",
                [
                    JavaRedisCodec._encode_value(item, java_type=item_java_type, nested=True)
                    for item in value
                ],
            ]
        if isinstance(value, list | tuple):
            return [
                "java.util.ArrayList",
                [
                    JavaRedisCodec._encode_value(item, java_type=item_java_type, nested=True)
                    for item in value
                ],
            ]
        return value

    @staticmethod
    def _decode_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): JavaRedisCodec._decode_value(item)
                for key, item in value.items()
                if key != "@class"
            }
        if isinstance(value, list):
            if len(value) == 2 and isinstance(value[0], str) and value[0].startswith("java."):
                type_name, payload = value
                if type_name == "java.util.Date":
                    timezone = ZoneInfo(get_settings().timezone)
                    return datetime.fromtimestamp(float(payload) / 1000, timezone).replace(tzinfo=None)
                if type_name in {
                    "java.util.ArrayList",
                    "java.util.LinkedList",
                    "java.util.HashSet",
                    "java.util.LinkedHashSet",
                } and isinstance(payload, list):
                    return [JavaRedisCodec._decode_value(item) for item in payload]
                return JavaRedisCodec._decode_value(payload)
            return [JavaRedisCodec._decode_value(item) for item in value]
        return value


def _snake_to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(get_settings().redis_url, decode_responses=False)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


async def redis_ping() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:
        return False


async def java_get(key: str) -> Any:
    return JavaRedisCodec.decode(await cast(Any, get_redis().get(key)))


async def java_set(
    key: str,
    value: Any,
    ttl_seconds: int | None = None,
    *,
    java_type: str | None = None,
    item_java_type: str | None = None,
) -> None:
    await cast(Any, get_redis().set)(
        key,
        JavaRedisCodec.encode(value, java_type=java_type, item_java_type=item_java_type),
        ex=ttl_seconds,
    )


async def java_hget(key: str, field: str) -> Any:
    return JavaRedisCodec.decode(await cast(Any, get_redis().hget(key, field)))


async def java_hset(key: str, field: str, value: Any, ttl_seconds: int = 86400) -> None:
    redis = get_redis()
    await cast(Any, redis.hset)(key, field, JavaRedisCodec.encode(value))
    await cast(Any, redis.expire)(key, ttl_seconds)


@asynccontextmanager
async def distributed_lock(name: str, ttl_seconds: int) -> AsyncIterator[bool]:
    lock = get_redis().lock(name, timeout=ttl_seconds, blocking_timeout=0)
    acquired = bool(await lock.acquire(blocking=False))
    renewal: asyncio.Task[None] | None = None
    if acquired:
        renewal = asyncio.create_task(_renew_lock(lock, ttl_seconds))
    try:
        yield acquired
    finally:
        if renewal is not None:
            renewal.cancel()
            with suppress(asyncio.CancelledError):
                await renewal
        if acquired:
            try:
                await lock.release()
            except Exception:
                logger.warning("Lost ownership of distributed lock %s before release", name, exc_info=True)


async def _renew_lock(lock: Any, ttl_seconds: int) -> None:
    """Keep a held job lock alive until its owner leaves the context."""

    interval = max(float(ttl_seconds) / 3, 0.25)
    while True:
        await asyncio.sleep(interval)
        try:
            await lock.extend(ttl_seconds, replace_ttl=True)
        except Exception:
            logger.exception("Unable to renew distributed lock; duplicate execution protection is at risk")
            return
