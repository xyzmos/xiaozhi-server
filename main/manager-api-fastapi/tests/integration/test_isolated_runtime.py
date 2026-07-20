from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.redis import close_redis, distributed_lock

pytestmark = pytest.mark.integration


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is required; use scripts/isolated-env.sh env")
    return value


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = _required_environment("TEST_FASTAPI_DATABASE_URL")
    selected = create_async_engine(value, pool_pre_ping=True)
    try:
        yield selected
    finally:
        await selected.dispose()


@pytest.fixture
async def isolated_redis() -> AsyncIterator[Redis]:
    value = _required_environment("TEST_FASTAPI_REDIS_URL")
    selected = Redis.from_url(value, decode_responses=True)
    try:
        if not await selected.ping():
            pytest.fail("isolated Redis did not answer PING")
        yield selected
    finally:
        await selected.delete(
            "contract:test:ttl",
            "contract:test:persistent-sentinel",
            "jobs:knowledge-document-status",
            "jobs:contract-renewal",
        )
        await selected.aclose()


@pytest.mark.asyncio
async def test_mysql_transaction_rollback(engine: AsyncEngine) -> None:
    parameter_id = 9_007_199_254_740_980
    code = "contract.test.rollback"
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM sys_params WHERE param_code=:code"), {"code": code})

    with pytest.raises(RuntimeError, match="force rollback"):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO sys_params(id,param_code,param_value,value_type,param_type) "
                    "VALUES(:id,:code,'before-rollback','string',1)"
                ),
                {"id": parameter_id, "code": code},
            )
            raise RuntimeError("force rollback")

    async with engine.connect() as connection:
        count = await connection.scalar(
            text("SELECT COUNT(*) FROM sys_params WHERE param_code=:code"),
            {"code": code},
        )
    assert count == 0


@pytest.mark.asyncio
async def test_mysql_select_for_update_serializes_concurrent_writers(engine: AsyncEngine) -> None:
    parameter_id = 9_007_199_254_740_981
    code = "contract.test.for-update"
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM sys_params WHERE param_code=:code"), {"code": code})
        await connection.execute(
            text(
                "INSERT INTO sys_params(id,param_code,param_value,value_type,param_type) "
                "VALUES(:id,:code,'0','number',1)"
            ),
            {"id": parameter_id, "code": code},
        )

    first_has_lock = asyncio.Event()

    async def increment(*, hold_lock: bool) -> None:
        async with engine.begin() as connection:
            result = await connection.execute(
                text("SELECT param_value FROM sys_params WHERE param_code=:code FOR UPDATE"),
                {"code": code},
            )
            current = int(result.scalar_one())
            if hold_lock:
                first_has_lock.set()
                await asyncio.sleep(0.2)
            await connection.execute(
                text("UPDATE sys_params SET param_value=:value WHERE param_code=:code"),
                {"value": str(current + 1), "code": code},
            )

    first = asyncio.create_task(increment(hold_lock=True))
    await first_has_lock.wait()
    second = asyncio.create_task(increment(hold_lock=False))
    await asyncio.gather(first, second)

    async with engine.connect() as connection:
        value = await connection.scalar(
            text("SELECT param_value FROM sys_params WHERE param_code=:code"),
            {"code": code},
        )
    assert value == "2"

    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM sys_params WHERE param_code=:code"), {"code": code})


@pytest.mark.asyncio
async def test_redis_ttl_expires_without_clearing_unrelated_keys(isolated_redis: Redis) -> None:
    await isolated_redis.set("contract:test:persistent-sentinel", "preserved")
    await isolated_redis.set("contract:test:ttl", "temporary", ex=1)
    ttl = await isolated_redis.ttl("contract:test:ttl")
    assert 0 < ttl <= 1
    await asyncio.sleep(1.1)
    assert await isolated_redis.get("contract:test:ttl") is None
    assert await isolated_redis.get("contract:test:persistent-sentinel") == "preserved"


@pytest.mark.asyncio
async def test_job_distributed_lock_allows_one_concurrent_execution(
    isolated_redis: Redis,
) -> None:
    await isolated_redis.delete("jobs:knowledge-document-status")
    executions = 0
    entered = asyncio.Event()

    async def contender() -> bool:
        nonlocal executions
        async with distributed_lock("jobs:knowledge-document-status", 10) as acquired:
            if not acquired:
                return False
            executions += 1
            entered.set()
            await asyncio.sleep(0.2)
            return True

    try:
        first = asyncio.create_task(contender())
        await asyncio.wait_for(entered.wait(), timeout=2)
        second = asyncio.create_task(contender())
        results = await asyncio.gather(first, second)
        assert list(results) == [True, False]
        assert executions == 1
        assert await isolated_redis.exists("jobs:knowledge-document-status") == 0
    finally:
        await close_redis()


@pytest.mark.asyncio
async def test_job_distributed_lock_watchdog_renews_long_execution(
    isolated_redis: Redis,
) -> None:
    """A job longer than its initial lease must remain single-instance."""

    key = "jobs:contract-renewal"
    await isolated_redis.delete(key)
    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def first_owner() -> bool:
        async with distributed_lock(key, 1) as acquired:
            assert acquired
            first_entered.set()
            await release_first.wait()
            return acquired

    first = asyncio.create_task(first_owner())
    try:
        await asyncio.wait_for(first_entered.wait(), timeout=2)
        # Cross the original one-second lease.  The watchdog should have extended
        # it, so another worker still cannot enter.
        await asyncio.sleep(1.25)
        async with distributed_lock(key, 1) as second_acquired:
            assert not second_acquired
        release_first.set()
        assert await first
        assert await isolated_redis.exists(key) == 0
    finally:
        release_first.set()
        if not first.done():
            await first
        await close_redis()


class _FakeFactory:
    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[object]:
        yield object()


@pytest.mark.asyncio
async def test_knowledge_job_function_is_single_instance(
    isolated_redis: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.jobs import tasks
    from app.services.knowledge import KnowledgeDocumentService

    await isolated_redis.delete("jobs:knowledge-document-status")
    executions = 0
    entered = asyncio.Event()

    async def fake_sync(_: KnowledgeDocumentService) -> int:
        nonlocal executions
        executions += 1
        entered.set()
        await asyncio.sleep(0.2)
        return 1

    monkeypatch.setattr(tasks, "get_session_factory", lambda: _FakeFactory())
    monkeypatch.setattr(KnowledgeDocumentService, "sync_running", fake_sync)
    try:
        first = asyncio.create_task(tasks.sync_running_knowledge_documents())
        await asyncio.wait_for(entered.wait(), timeout=2)
        second = asyncio.create_task(tasks.sync_running_knowledge_documents())
        results = await asyncio.gather(first, second)
        assert list(results) == [1, 0]
        assert executions == 1
    finally:
        await close_redis()


@pytest.mark.asyncio
async def test_redis_java_hash_default_ttl(isolated_redis: Redis) -> None:
    from app.core.redis import java_hset

    try:
        await java_hset("contract:test:java-hash", "field", {"id": 9_007_199_254_740_993})
        ttl = await isolated_redis.ttl("contract:test:java-hash")
        assert 86_390 <= ttl <= 86_400
        raw = await cast(Any, isolated_redis.hget)("contract:test:java-hash", "field")
        assert raw is not None
        await isolated_redis.delete("contract:test:java-hash")
    finally:
        await close_redis()
