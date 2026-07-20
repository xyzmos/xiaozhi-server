from __future__ import annotations

# Every interpolated SQL fragment below is a module constant or a service-side allowlist.
# ruff: noqa: S608
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Repository

DEVICE_COLUMNS = (
    "id, user_id, mac_address, last_connected_at, auto_update, board, alias, "
    "agent_id, app_version, sort, updater, update_date, creator, create_date"
)
OTA_COLUMNS = (
    "id, firmware_name, type, version, size, remark, firmware_path, sort, "
    "updater, update_date, creator, create_date"
)
ADDRESS_BOOK_COLUMNS = (
    "mac_address, target_mac, alias, has_permission, creator, create_date, updater, update_date"
)


class DeviceRepository(Repository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_device(self, device_id: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            f"SELECT {DEVICE_COLUMNS} FROM ai_device WHERE id = :id LIMIT 1",
            {"id": device_id},
        )

    async def get_device_by_mac(self, mac_address: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            f"SELECT {DEVICE_COLUMNS} FROM ai_device WHERE mac_address = :mac_address LIMIT 1",
            {"mac_address": mac_address},
        )

    async def get_user_devices(self, user_id: int, agent_id: str) -> list[dict[str, Any]]:
        return await self.fetch_all(
            f"SELECT {DEVICE_COLUMNS} FROM ai_device WHERE user_id = :user_id AND agent_id = :agent_id",
            {"user_id": user_id, "agent_id": agent_id},
        )

    async def insert_device(self, values: Mapping[str, Any]) -> None:
        await self.execute(
            "INSERT INTO ai_device "
            "(id, user_id, mac_address, last_connected_at, auto_update, board, alias, agent_id, app_version, "
            "sort, updater, update_date, creator, create_date) "
            "VALUES (:id, :user_id, :mac_address, :last_connected_at, :auto_update, :board, :alias, :agent_id, "
            ":app_version, :sort, :updater, :update_date, :creator, :create_date)",
            values,
        )

    async def update_device_info(
        self,
        device_id: str,
        *,
        auto_update: int | None,
        alias: str | None,
        updater: int,
        now: datetime,
    ) -> int:
        assignments = ["updater = :updater", "update_date = :now"]
        params: dict[str, Any] = {"id": device_id, "updater": updater, "now": now}
        if auto_update is not None:
            assignments.append("auto_update = :auto_update")
            params["auto_update"] = auto_update
        if alias is not None:
            assignments.append("alias = :alias")
            params["alias"] = alias
        return await self.execute(
            f"UPDATE ai_device SET {', '.join(assignments)} WHERE id = :id",
            params,
        )

    async def update_connection(
        self,
        device_id: str,
        *,
        app_version: str | None,
        now: datetime,
    ) -> int:
        if app_version is None or not app_version.strip():
            return await self.execute(
                "UPDATE ai_device SET last_connected_at = :now WHERE id = :id",
                {"id": device_id, "now": now},
            )
        return await self.execute(
            "UPDATE ai_device SET last_connected_at = :now, app_version = :app_version WHERE id = :id",
            {"id": device_id, "now": now, "app_version": app_version},
        )

    async def delete_device_for_user(self, device_id: str, user_id: int) -> int:
        return await self.execute(
            "DELETE FROM ai_device WHERE id = :id AND user_id = :user_id",
            {"id": device_id, "user_id": user_id},
        )

    async def get_address_book(self, mac_address: str) -> list[dict[str, Any]]:
        return await self.fetch_all(
            f"SELECT {ADDRESS_BOOK_COLUMNS} FROM ai_device_address_book "
            "WHERE mac_address = :mac_address ORDER BY update_date DESC",
            {"mac_address": mac_address},
        )

    async def get_all_address_book(self) -> list[dict[str, Any]]:
        return await self.fetch_all(f"SELECT {ADDRESS_BOOK_COLUMNS} FROM ai_device_address_book")

    async def get_address_book_record(self, mac_address: str, target_mac: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            f"SELECT {ADDRESS_BOOK_COLUMNS} FROM ai_device_address_book "
            "WHERE mac_address = :mac_address AND target_mac = :target_mac LIMIT 1",
            {"mac_address": mac_address, "target_mac": target_mac},
        )

    async def get_aliases(self, mac_address: str) -> list[str]:
        rows = await self.fetch_all(
            "SELECT alias FROM ai_device_address_book WHERE mac_address = :mac_address",
            {"mac_address": mac_address},
        )
        return [str(row["alias"]) for row in rows if row.get("alias") not in (None, "")]

    async def insert_address_book(
        self,
        *,
        mac_address: str,
        target_mac: str,
        alias: str | None,
        has_permission: bool | None,
        actor: int,
        now: datetime,
    ) -> None:
        await self.execute(
            "INSERT INTO ai_device_address_book "
            "(mac_address, target_mac, alias, has_permission, creator, create_date, updater, update_date) "
            "VALUES (:mac_address, :target_mac, :alias, :has_permission, :actor, :now, :actor, :now)",
            {
                "mac_address": mac_address,
                "target_mac": target_mac,
                "alias": alias,
                "has_permission": has_permission,
                "actor": actor,
                "now": now,
            },
        )

    async def update_address_alias(
        self,
        mac_address: str,
        target_mac: str,
        alias: str | None,
        *,
        now: datetime,
    ) -> int:
        return await self.execute(
            "UPDATE ai_device_address_book SET alias = :alias, update_date = :now "
            "WHERE mac_address = :mac_address AND target_mac = :target_mac",
            {
                "mac_address": mac_address,
                "target_mac": target_mac,
                "alias": alias,
                "now": now,
            },
        )

    async def update_address_permission(
        self,
        mac_address: str,
        target_mac: str,
        has_permission: bool,
        *,
        now: datetime,
    ) -> int:
        return await self.execute(
            "UPDATE ai_device_address_book "
            "SET has_permission = :has_permission, update_date = :now "
            "WHERE mac_address = :mac_address AND target_mac = :target_mac",
            {
                "mac_address": mac_address,
                "target_mac": target_mac,
                "has_permission": has_permission,
                "now": now,
            },
        )

    async def delete_address_books_for_macs(self, mac_addresses: Sequence[str]) -> int:
        if not mac_addresses:
            return 0
        placeholders = ", ".join(f":mac_{index}" for index in range(len(mac_addresses)))
        params = {f"mac_{index}": mac for index, mac in enumerate(mac_addresses)}
        return await self.execute(
            f"DELETE FROM ai_device_address_book WHERE mac_address IN ({placeholders}) "
            f"OR target_mac IN ({placeholders})",
            params,
        )

    async def count_ota(self, firmware_name: str | None = None) -> int:
        where = ""
        params: dict[str, Any] = {}
        if firmware_name is not None and firmware_name.strip():
            where = " WHERE firmware_name LIKE :firmware_name"
            params["firmware_name"] = f"%{firmware_name}%"
        return int(await self.scalar(f"SELECT COUNT(*) FROM ai_ota{where}", params) or 0)

    async def list_ota(
        self,
        *,
        page: int,
        limit: int,
        firmware_name: str | None,
        order_fields: Sequence[str],
        ascending: bool,
    ) -> list[dict[str, Any]]:
        where = ""
        params: dict[str, Any] = {"limit": limit, "offset": max(page - 1, 0) * limit}
        if firmware_name is not None and firmware_name.strip():
            where = " WHERE firmware_name LIKE :firmware_name"
            params["firmware_name"] = f"%{firmware_name}%"
        direction = "ASC" if ascending else "DESC"
        order_by = ", ".join(f"{field} {direction}" for field in order_fields)
        return await self.fetch_all(
            f"SELECT {OTA_COLUMNS} FROM ai_ota{where} ORDER BY {order_by} LIMIT :limit OFFSET :offset",
            params,
        )

    async def get_ota(self, ota_id: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            f"SELECT {OTA_COLUMNS} FROM ai_ota WHERE id = :id LIMIT 1",
            {"id": ota_id},
        )

    async def get_first_ota_by_type(self, ota_type: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            f"SELECT {OTA_COLUMNS} FROM ai_ota WHERE type = :type LIMIT 1",
            {"type": ota_type},
        )

    async def get_latest_ota(self, ota_type: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            f"SELECT {OTA_COLUMNS} FROM ai_ota WHERE type = :type ORDER BY update_date DESC LIMIT 1",
            {"type": ota_type},
        )

    async def count_duplicate_ota(self, *, ota_id: str, ota_type: str | None, version: str | None) -> int:
        return int(
            await self.scalar(
                "SELECT COUNT(*) FROM ai_ota WHERE type = :type AND version = :version AND id <> :id",
                {"id": ota_id, "type": ota_type, "version": version},
            )
            or 0
        )

    async def insert_ota(self, values: Mapping[str, Any]) -> None:
        await self.execute(
            "INSERT INTO ai_ota "
            "(id, firmware_name, type, version, size, remark, firmware_path, sort, updater, update_date, creator, "
            "create_date) VALUES (:id, :firmware_name, :type, :version, :size, :remark, :firmware_path, :sort, "
            ":updater, :update_date, :creator, :create_date)",
            values,
        )

    async def update_ota(self, ota_id: str, values: Mapping[str, Any]) -> int:
        allowed = {
            "firmware_name",
            "type",
            "version",
            "size",
            "remark",
            "firmware_path",
            "sort",
            "updater",
            "update_date",
            "creator",
            "create_date",
        }
        selected = {key: value for key, value in values.items() if key in allowed and value is not None}
        if not selected:
            return 0
        assignments = ", ".join(f"{key} = :{key}" for key in selected)
        return await self.execute(
            f"UPDATE ai_ota SET {assignments} WHERE id = :id",
            {"id": ota_id, **selected},
        )

    async def delete_ota(self, ids: Sequence[str]) -> int:
        if not ids:
            return 0
        placeholders = ", ".join(f":id_{index}" for index in range(len(ids)))
        params = {f"id_{index}": value for index, value in enumerate(ids)}
        return await self.execute(f"DELETE FROM ai_ota WHERE id IN ({placeholders})", params)
