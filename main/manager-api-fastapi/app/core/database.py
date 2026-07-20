from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import Result, TextClause, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def configure_database(settings: Settings | None = None) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    global _engine, _session_factory
    selected = settings or get_settings()
    engine_options: dict[str, Any] = {"pool_pre_ping": True}
    if not selected.database_url.startswith("sqlite"):
        engine_options.update(pool_size=selected.database_pool_size, max_overflow=selected.database_max_overflow)
    _engine = create_async_engine(selected.database_url, **engine_options)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine, _session_factory


def get_engine() -> AsyncEngine:
    if _engine is None:
        return configure_database()[0]
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        return configure_database()[1]
    return _session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


@asynccontextmanager
async def transaction() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session, session.begin():
        yield session


async def dispose_database() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


class Repository:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def statement(sql: str | TextClause) -> TextClause:
        return text(sql) if isinstance(sql, str) else sql

    async def fetch_one(self, sql: str | TextClause, params: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        result = await self.session.execute(self.statement(sql), dict(params or {}))
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def fetch_all(self, sql: str | TextClause, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        result = await self.session.execute(self.statement(sql), dict(params or {}))
        return [dict(row) for row in result.mappings().all()]

    async def scalar(self, sql: str | TextClause, params: Mapping[str, Any] | None = None) -> Any:
        result = await self.session.execute(self.statement(sql), dict(params or {}))
        return result.scalar_one_or_none()

    async def execute(self, sql: str | TextClause, params: Mapping[str, Any] | None = None) -> int:
        result: Result[Any] = await self.session.execute(self.statement(sql), dict(params or {}))
        return int(getattr(result, "rowcount", 0) or 0)

    async def execute_many(self, sql: str | TextClause, params: Sequence[Mapping[str, Any]]) -> int:
        if not params:
            return 0
        result: Result[Any] = await self.session.execute(self.statement(sql), [dict(item) for item in params])
        return int(getattr(result, "rowcount", 0) or 0)


async def database_ping() -> bool:
    try:
        async with get_session_factory()() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
