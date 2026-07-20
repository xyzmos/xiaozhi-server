from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import java_hget, java_hset

logger = logging.getLogger(__name__)


class SystemParamService:
    CACHE_KEY = "sys:params"

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_value(self, code: str, *, from_cache: bool = True) -> str | None:
        if from_cache:
            try:
                cached = await java_hget(self.CACHE_KEY, code)
                if cached is not None:
                    return str(cached)
            except Exception:
                logger.warning("Redis parameter cache read failed for %s", code, exc_info=True)
        result = await self.session.execute(
            text("SELECT param_value FROM sys_params WHERE param_code = :code LIMIT 1"),
            {"code": code},
        )
        value = result.scalar_one_or_none()
        if value is not None and from_cache:
            try:
                await java_hset(self.CACHE_KEY, code, str(value))
            except Exception:
                logger.warning("Redis parameter cache write failed for %s", code, exc_info=True)
        return None if value is None else str(value)

    async def set_value(self, code: str, value: str) -> int:
        result = await self.session.execute(
            text(
                "UPDATE sys_params SET param_value = :value, update_date = CURRENT_TIMESTAMP WHERE param_code = :code"
            ),
            {"code": code, "value": value},
        )
        try:
            await java_hset(self.CACHE_KEY, code, value)
        except Exception:
            logger.warning("Redis parameter cache write failed for %s", code, exc_info=True)
        return int(getattr(result, "rowcount", 0) or 0)
