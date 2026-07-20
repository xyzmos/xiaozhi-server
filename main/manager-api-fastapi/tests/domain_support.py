from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.hashes: dict[str, dict[str, Any]] = {}
        self.expirations: dict[str, float] = {}

    def _purge(self, key: str) -> None:
        expiry = self.expirations.get(key)
        if expiry is not None and expiry <= time.monotonic():
            self.values.pop(key, None)
            self.hashes.pop(key, None)
            self.expirations.pop(key, None)

    async def get(self, key: str) -> Any:
        self._purge(key)
        return self.values.get(key)

    async def set(
        self,
        key: str,
        value: Any,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        self._purge(key)
        if nx and key in self.values:
            return None
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = time.monotonic() + ex
        return True

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            deleted += int(key in self.values or key in self.hashes)
            self.values.pop(key, None)
            self.hashes.pop(key, None)
            self.expirations.pop(key, None)
        return deleted

    async def incr(self, key: str) -> int:
        self._purge(key)
        raw = self.values.get(key, b"0")
        if isinstance(raw, bytes):
            raw = raw.decode()
        value = int(raw) + 1
        self.values[key] = str(value).encode()
        return value

    async def expire(self, key: str, seconds: int) -> bool:
        if key not in self.values and key not in self.hashes:
            return False
        self.expirations[key] = time.monotonic() + seconds
        return True

    async def ttl(self, key: str) -> int:
        self._purge(key)
        if key not in self.values and key not in self.hashes:
            return -2
        expiry = self.expirations.get(key)
        return -1 if expiry is None else max(0, int(expiry - time.monotonic()))

    async def hget(self, key: str, field: str) -> Any:
        self._purge(key)
        return self.hashes.get(key, {}).get(field)

    async def hset(self, key: str, field: str, value: Any) -> int:
        created = field not in self.hashes.setdefault(key, {})
        self.hashes[key][field] = value
        return int(created)

    async def hdel(self, key: str, *fields: str) -> int:
        values = self.hashes.get(key, {})
        deleted = 0
        for field in fields:
            deleted += int(field in values)
            values.pop(field, None)
        return deleted


@asynccontextmanager
async def sqlite_session(statements: list[str]) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        for statement in statements:
            await connection.execute(text(statement))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
