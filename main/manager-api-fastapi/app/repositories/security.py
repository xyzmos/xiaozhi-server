from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Repository


class SecurityRepository(Repository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_param_value(self, code: str) -> str | None:
        value = await self.scalar(
            "SELECT param_value FROM sys_params WHERE param_code = :code LIMIT 1",
            {"code": code},
        )
        return None if value is None else str(value)

    async def get_mobile_area_items(self) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT d.dict_label AS name, d.dict_value AS `key` "
            "FROM sys_dict_data d "
            "LEFT JOIN sys_dict_type t ON d.dict_type_id = t.id "
            "WHERE t.dict_type = :dict_type ORDER BY d.sort ASC",
            {"dict_type": "MOBILE_AREA"},
        )

    async def get_user_by_username(self, username: str | None) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT id, username, password, super_admin, status, creator, create_date, updater, update_date "
            "FROM sys_user WHERE username = :username LIMIT 1",
            {"username": username},
        )

    async def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT id, username, password, super_admin, status, creator, create_date, updater, update_date "
            "FROM sys_user WHERE id = :id LIMIT 1",
            {"id": user_id},
        )

    async def count_users(self) -> int:
        return int(await self.scalar("SELECT COUNT(*) FROM sys_user") or 0)

    async def insert_user(
        self,
        *,
        user_id: int,
        username: str | None,
        password: str,
        super_admin: int,
        now: datetime,
    ) -> None:
        await self.execute(
            "INSERT INTO sys_user "
            "(id, username, password, super_admin, status, creator, create_date, updater, update_date) "
            "VALUES (:id, :username, :password, :super_admin, 1, NULL, :now, NULL, :now)",
            {
                "id": user_id,
                "username": username,
                "password": password,
                "super_admin": super_admin,
                "now": now,
            },
        )

    async def get_token_by_user_id(self, user_id: int, *, for_update: bool = False) -> dict[str, Any] | None:
        sql = (
            "SELECT id, user_id, token, expire_date, update_date, create_date "
            "FROM sys_user_token WHERE user_id = :user_id LIMIT 1 FOR UPDATE"
            if for_update and self._supports_for_update()
            else "SELECT id, user_id, token, expire_date, update_date, create_date "
            "FROM sys_user_token WHERE user_id = :user_id LIMIT 1"
        )
        return await self.fetch_one(
            sql,
            {"user_id": user_id},
        )

    async def insert_token(
        self,
        *,
        token_id: int,
        user_id: int,
        token: str,
        now: datetime,
        expire_date: datetime,
    ) -> None:
        await self.execute(
            "INSERT INTO sys_user_token (id, user_id, token, expire_date, update_date, create_date) "
            "VALUES (:id, :user_id, :token, :expire_date, :now, :now)",
            {
                "id": token_id,
                "user_id": user_id,
                "token": token,
                "expire_date": expire_date,
                "now": now,
            },
        )

    async def update_token(self, *, token_id: int, token: str, now: datetime, expire_date: datetime) -> None:
        await self.execute(
            "UPDATE sys_user_token SET token = :token, expire_date = :expire_date, update_date = :now "
            "WHERE id = :id",
            {"id": token_id, "token": token, "expire_date": expire_date, "now": now},
        )

    async def update_password(
        self,
        user_id: int,
        password_hash: str,
        now: datetime,
        *,
        preserve_audit_fields: bool = False,
    ) -> int:
        return await self.execute(
            "UPDATE sys_user SET password = :password, "
            "update_date = CASE WHEN :preserve_audit = 1 THEN update_date ELSE :now END WHERE id = :id",
            {
                "id": user_id,
                "password": password_hash,
                "now": now,
                "preserve_audit": int(preserve_audit_fields),
            },
        )

    async def expire_user_token(self, user_id: int, expire_date: datetime) -> int:
        return await self.execute(
            "UPDATE sys_user_token SET expire_date = :expire_date WHERE user_id = :user_id",
            {"user_id": user_id, "expire_date": expire_date},
        )

    def _supports_for_update(self) -> bool:
        bind = self.session.get_bind()
        return bind.dialect.name != "sqlite"


async def raw_user_token(session: AsyncSession, token: str) -> dict[str, Any] | None:
    result = await session.execute(
        text(
            "SELECT t.id AS token_id, t.user_id, t.token, t.expire_date, "
            "u.username, u.super_admin, u.status "
            "FROM sys_user_token t JOIN sys_user u ON u.id = t.user_id "
            "WHERE t.token = :token LIMIT 1"
        ),
        {"token": token},
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None
