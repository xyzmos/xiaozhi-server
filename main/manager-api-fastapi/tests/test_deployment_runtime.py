from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.worker import _finish_tasks, _fixed_delay_loop
from app.services.device import DeviceService, redis_set
from tests.domain_support import FakeRedis

TARGET_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = TARGET_ROOT.parents[1]


def test_application_lifespan_starts_and_shuts_down_without_binding_a_port(tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    code = (
        "from fastapi.testclient import TestClient; "
        "from app.main import app; "
        "client=TestClient(app); "
        "client.__enter__(); "
        "response=client.get('/xiaozhi/health/live'); "
        "assert response.status_code == 200, response.text; "
        "client.__exit__(None, None, None)"
    )
    environment = {
        **os.environ,
        "APP_ENVIRONMENT": "test",
        "APP_ALLOW_START_WITHOUT_DEPENDENCIES": "true",
        "APP_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "APP_REDIS_URL": "redis://127.0.0.1:1/15",
        "APP_UPLOAD_DIR": str(upload_dir),
        "APP_JAVA_RESOURCES_DIR": str(REPOSITORY_ROOT / "main" / "manager-api" / "src" / "main" / "resources"),
    }
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=TARGET_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert upload_dir.is_dir()


@pytest.mark.asyncio
async def test_readiness_reports_dependency_state_with_real_http_status(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main as main_module

    async def available() -> bool:
        return True

    async def unavailable() -> bool:
        return False

    monkeypatch.setattr(main_module, "database_ping", available)
    monkeypatch.setattr(main_module, "redis_ping", unavailable)
    monkeypatch.setattr(main_module, "upload_storage_ready", lambda: True)
    failed = await main_module.readiness()
    assert failed.status_code == 503
    assert json.loads(failed.body) == {
        "code": 503,
        "msg": "dependencies unavailable",
        "data": {"database": True, "redis": False, "uploads": True},
    }

    monkeypatch.setattr(main_module, "redis_ping", available)
    ready = await main_module.readiness()
    assert ready.status_code == 200
    assert json.loads(ready.body)["data"] == {
        "database": True,
        "redis": True,
        "uploads": True,
    }

    monkeypatch.setattr(main_module, "upload_storage_ready", lambda: False)
    unwritable = await main_module.readiness()
    assert unwritable.status_code == 503
    assert json.loads(unwritable.body)["data"] == {
        "database": True,
        "redis": True,
        "uploads": False,
    }
    assert (await main_module.liveness()).status_code == 200


@pytest.mark.asyncio
async def test_job_shutdown_drains_active_work_before_cancelling() -> None:
    stop = asyncio.Event()
    started = asyncio.Event()
    release = asyncio.Event()

    async def operation() -> int:
        started.set()
        await release.wait()
        return 1

    task = asyncio.create_task(
        _fixed_delay_loop(stop, operation, name="test", initial_delay=0, delay=60)
    )
    await started.wait()
    stop.set()
    drain = asyncio.create_task(_finish_tasks([task], timeout=1))
    await asyncio.sleep(0)
    assert not drain.done()
    release.set()
    assert await drain is True
    assert task.done() and not task.cancelled()


@pytest.mark.asyncio
async def test_fixed_delay_job_runs_again_after_python_310_wait_timeout() -> None:
    stop = asyncio.Event()
    calls = 0

    async def operation() -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            stop.set()
        return calls

    await asyncio.wait_for(
        _fixed_delay_loop(stop, operation, name="timeout-regression", initial_delay=0, delay=0.01),
        timeout=1,
    )
    assert calls == 2


@pytest.mark.asyncio
async def test_job_shutdown_cancels_only_after_timeout() -> None:
    task = asyncio.create_task(asyncio.sleep(60))
    assert await _finish_tasks([task], timeout=0.01) is False
    assert task.cancelled()


@pytest.mark.asyncio
async def test_configured_upload_volume_keeps_java_relative_database_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mounted = tmp_path / "mounted-uploads"
    monkeypatch.setattr(
        "app.services.device.get_settings",
        lambda: SimpleNamespace(upload_dir=mounted),
    )
    redis = cast(Redis, FakeRedis())
    service = DeviceService(cast(AsyncSession, object()), redis_client=redis)
    content = b"deployment-upload"
    digest = hashlib.md5(content, usedforsecurity=False).hexdigest()
    java_path = f"uploadfile/{digest}.bin"

    assert await service.save_firmware_file(filename="firmware.bin", content=content) == java_path
    assert (mounted / f"{digest}.bin").read_bytes() == content
    assert not (tmp_path / java_path).exists()

    await redis_set("ota:id:volume-test", f"file:{java_path}", client=redis)
    resolved = await service.resolve_ota_download("volume-test")
    assert resolved is not None
    assert resolved[0] == mounted / f"{digest}.bin"
    assert resolved[0].read_bytes() == content
