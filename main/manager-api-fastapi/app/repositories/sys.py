from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Repository


class SysRepository(Repository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def page_users(self, *, mobile: str | None, page: int, limit: int) -> tuple[list[dict[str, Any]], int]:
        pattern = f"%{mobile}%" if mobile else None
        params = {"mobile": pattern, "offset": (page - 1) * limit, "limit": limit}
        total = int(
            await self.scalar(
                "SELECT COUNT(*) FROM sys_user WHERE (:mobile IS NULL OR username LIKE :mobile)",
                params,
            )
            or 0
        )
        rows = await self.fetch_all(
            "SELECT u.id, u.username, u.status, u.create_date, "
            "(SELECT COUNT(*) FROM ai_device d WHERE d.user_id = u.id) AS device_count "
            "FROM sys_user u WHERE (:mobile IS NULL OR u.username LIKE :mobile) "
            "ORDER BY u.id ASC LIMIT :limit OFFSET :offset",
            params,
        )
        return rows, total

    async def reset_user_password(
        self,
        user_id: int,
        password_hash: str,
        updater: int,
        now: datetime,
    ) -> int:
        return await self.execute(
            "UPDATE sys_user SET password = :password, updater = :updater, update_date = :now WHERE id = :id",
            {"id": user_id, "password": password_hash, "updater": updater, "now": now},
        )

    async def change_user_status(self, status: int, user_ids: list[int], updater: int, now: datetime) -> int:
        statement = text(
            "UPDATE sys_user SET status = :status, updater = :updater, update_date = :now WHERE id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        return await self.execute(
            statement,
            {"status": status, "updater": updater, "now": now, "ids": user_ids},
        )

    async def delete_user_cascade(self, user_id: int) -> None:
        agent_rows = await self.fetch_all("SELECT id FROM ai_agent WHERE user_id = :user_id", {"user_id": user_id})
        agent_ids = [str(row["id"]) for row in agent_rows]
        await self.execute("DELETE FROM sys_user WHERE id = :id", {"id": user_id})
        await self.execute("DELETE FROM ai_device WHERE user_id = :id", {"id": user_id})
        for agent_id in agent_ids:
            audio_rows = await self.fetch_all(
                "SELECT DISTINCT audio_id FROM ai_agent_chat_history "
                "WHERE agent_id = :agent_id AND audio_id IS NOT NULL",
                {"agent_id": agent_id},
            )
            audio_ids = [str(row["audio_id"]) for row in audio_rows]
            if audio_ids:
                statement = text("DELETE FROM ai_agent_chat_audio WHERE id IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                )
                await self.execute(statement, {"ids": audio_ids})
            for table in (
                "ai_agent_chat_history",
                "ai_agent_plugin_mapping",
                "ai_agent_context_provider",
                "ai_agent_correct_word_mapping",
                "ai_agent_tag_relation",
                "ai_agent_snapshot",
            ):
                # Table names are a closed list mirroring AgentServiceImpl.deleteAgent.
                await self.execute(
                    f"DELETE FROM {table} WHERE agent_id = :agent_id",  # noqa: S608 - closed table list above
                    {"agent_id": agent_id},
                )
            await self.execute("DELETE FROM ai_device WHERE agent_id = :agent_id", {"agent_id": agent_id})
            await self.execute("DELETE FROM ai_agent WHERE id = :agent_id", {"agent_id": agent_id})

    async def page_devices(
        self,
        *,
        keywords: str | None,
        page: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        pattern = f"%{keywords}%" if keywords else None
        params = {"keywords": pattern, "offset": (page - 1) * limit, "limit": limit}
        total = int(
            await self.scalar(
                "SELECT COUNT(*) FROM ai_device WHERE (:keywords IS NULL OR alias LIKE :keywords)",
                params,
            )
            or 0
        )
        rows = await self.fetch_all(
            "SELECT d.id, d.user_id, d.mac_address, d.last_connected_at, d.auto_update, d.board, d.alias, "
            "d.agent_id, d.app_version, d.sort, d.create_date, d.update_date, u.username AS bind_user_name "
            "FROM ai_device d LEFT JOIN sys_user u ON u.id = d.user_id "
            "WHERE (:keywords IS NULL OR d.alias LIKE :keywords) "
            "ORDER BY d.mac_address ASC LIMIT :limit OFFSET :offset",
            params,
        )
        return rows, total

    async def page_params(
        self,
        *,
        param_code: str | None,
        page: int,
        limit: int,
        order_field: str | None,
        order: str | None,
    ) -> tuple[list[dict[str, Any]], int]:
        pattern = f"%{param_code}%" if param_code else None
        params = {"pattern": pattern, "offset": (page - 1) * limit, "limit": limit}
        where = "param_type = 1 AND (:pattern IS NULL OR param_code LIKE :pattern OR remark LIKE :pattern)"
        total = int(await self.scalar(f"SELECT COUNT(*) FROM sys_params WHERE {where}", params) or 0)  # noqa: S608
        allowed = {
            "id": "id",
            "paramCode": "param_code",
            "paramValue": "param_value",
            "valueType": "value_type",
            "createDate": "create_date",
            "updateDate": "update_date",
        }
        order_column = allowed.get(order_field or "")
        order_clause = ""
        if order_column is not None:
            direction = "ASC" if (order or "").lower() == "asc" else "DESC"
            order_clause = f" ORDER BY {order_column} {direction}"
        sql = (
            "SELECT id, param_code, param_value, value_type, remark, create_date, update_date "  # noqa: S608
            f"FROM sys_params WHERE {where}{order_clause} LIMIT :limit OFFSET :offset"
        )
        return await self.fetch_all(sql, params), total  # noqa: S608

    async def list_config_params(self) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT id, param_code, param_value, value_type, remark, create_date, update_date "
            "FROM sys_params WHERE param_type = 1"
        )

    async def get_param(self, param_id: int) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT id, param_code, param_value, value_type, remark, create_date, update_date "
            "FROM sys_params WHERE id = :id",
            {"id": param_id},
        )

    async def get_param_value(self, code: str) -> str | None:
        value = await self.scalar("SELECT param_value FROM sys_params WHERE param_code = :code", {"code": code})
        return None if value is None else str(value)

    async def insert_param(
        self,
        *,
        param_id: int,
        param_code: str,
        param_value: str,
        value_type: str,
        remark: str | None,
        user_id: int,
        now: datetime,
    ) -> None:
        await self.execute(
            "INSERT INTO sys_params "
            "(id, param_code, param_value, value_type, param_type, remark, creator, create_date, updater, update_date) "
            "VALUES (:id, :code, :value, :value_type, 1, :remark, :user_id, :now, :user_id, :now)",
            {
                "id": param_id,
                "code": param_code,
                "value": param_value,
                "value_type": value_type,
                "remark": remark,
                "user_id": user_id,
                "now": now,
            },
        )

    async def update_param(
        self,
        *,
        param_id: int,
        param_code: str,
        param_value: str,
        value_type: str,
        remark: str | None,
        user_id: int,
        now: datetime,
    ) -> int:
        return await self.execute(
            "UPDATE sys_params SET param_code = :code, param_value = :value, value_type = :value_type, "
            "remark = CASE WHEN :has_remark = 1 THEN :remark ELSE remark END, updater = :user_id, update_date = :now "
            "WHERE id = :id",
            {
                "id": param_id,
                "code": param_code,
                "value": param_value,
                "value_type": value_type,
                "has_remark": int(remark is not None),
                "remark": remark,
                "user_id": user_id,
                "now": now,
            },
        )

    async def update_param_value_by_code(self, code: str, value: str, user_id: int, now: datetime) -> int:
        return await self.execute(
            "UPDATE sys_params SET param_value = :value, updater = :user_id, update_date = :now "
            "WHERE param_code = :code",
            {"code": code, "value": value, "user_id": user_id, "now": now},
        )

    async def param_codes_for_ids(self, ids: list[int]) -> list[str]:
        statement = text("SELECT param_code FROM sys_params WHERE id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        )
        rows = await self.fetch_all(statement, {"ids": ids})
        return [str(row["param_code"]) for row in rows]

    async def delete_params(self, ids: list[int]) -> int:
        statement = text("DELETE FROM sys_params WHERE id IN :ids").bindparams(bindparam("ids", expanding=True))
        return await self.execute(statement, {"ids": ids})

    async def delete_plugin_mapping_by_plugin_id(self, plugin_id: str) -> int:
        return await self.execute(
            "DELETE FROM ai_agent_plugin_mapping WHERE plugin_id = :plugin_id",
            {"plugin_id": plugin_id},
        )

    async def page_dict_types(
        self,
        *,
        dict_type: str | None,
        dict_name: str | None,
        page: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        params = {
            "dict_type": f"%{dict_type}%" if dict_type else None,
            "dict_name": f"%{dict_name}%" if dict_name else None,
            "offset": (page - 1) * limit,
            "limit": limit,
        }
        where = (
            "(:dict_type IS NULL OR t.dict_type LIKE :dict_type) "
            "AND (:dict_name IS NULL OR t.dict_name LIKE :dict_name)"
        )
        total = int(await self.scalar(f"SELECT COUNT(*) FROM sys_dict_type t WHERE {where}", params) or 0)  # noqa: S608
        rows = await self.fetch_all(
            "SELECT t.id, t.dict_type, t.dict_name, t.remark, t.sort, t.creator, t.create_date, t.updater, "  # noqa: S608
            "t.update_date, creator.username AS creator_name, updater.username AS updater_name "
            "FROM sys_dict_type t LEFT JOIN sys_user creator ON creator.id = t.creator "
            "LEFT JOIN sys_user updater ON updater.id = t.updater "
            f"WHERE {where} ORDER BY t.sort ASC LIMIT :limit OFFSET :offset",  # noqa: S608
            params,
        )
        return rows, total

    async def get_dict_type(self, type_id: int) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT id, dict_type, dict_name, remark, sort, creator, create_date, updater, update_date "
            "FROM sys_dict_type WHERE id = :id",
            {"id": type_id},
        )

    async def dict_type_exists(self, dict_type: str | None, *, exclude_id: int | None = None) -> bool:
        count = await self.scalar(
            "SELECT COUNT(*) FROM sys_dict_type WHERE dict_type = :dict_type "
            "AND (:exclude_id IS NULL OR id <> :exclude_id)",
            {"dict_type": dict_type, "exclude_id": exclude_id},
        )
        return int(count or 0) > 0

    async def insert_dict_type(
        self,
        *,
        type_id: int,
        dict_type: str | None,
        dict_name: str | None,
        remark: str | None,
        sort: int | None,
        user_id: int,
        now: datetime,
    ) -> None:
        await self.execute(
            "INSERT INTO sys_dict_type "
            "(id, dict_type, dict_name, remark, sort, creator, create_date, updater, update_date) "
            "VALUES (:id, :dict_type, :dict_name, :remark, :sort, :user_id, :now, :user_id, :now)",
            {
                "id": type_id,
                "dict_type": dict_type,
                "dict_name": dict_name,
                "remark": remark,
                "sort": sort,
                "user_id": user_id,
                "now": now,
            },
        )

    async def update_dict_type(
        self,
        *,
        type_id: int | None,
        dict_type: str | None,
        dict_name: str | None,
        remark: str | None,
        sort: int | None,
        user_id: int,
        now: datetime,
    ) -> int:
        return await self.execute(
            "UPDATE sys_dict_type SET "
            "dict_type = CASE WHEN :has_dict_type = 1 THEN :dict_type ELSE dict_type END, "
            "dict_name = CASE WHEN :has_dict_name = 1 THEN :dict_name ELSE dict_name END, "
            "remark = CASE WHEN :has_remark = 1 THEN :remark ELSE remark END, "
            "sort = CASE WHEN :has_sort = 1 THEN :sort ELSE sort END, updater = :user_id, update_date = :now "
            "WHERE id = :id",
            {
                "id": type_id,
                "has_dict_type": int(dict_type is not None),
                "dict_type": dict_type,
                "has_dict_name": int(dict_name is not None),
                "dict_name": dict_name,
                "has_remark": int(remark is not None),
                "remark": remark,
                "has_sort": int(sort is not None),
                "sort": sort,
                "user_id": user_id,
                "now": now,
            },
        )

    async def delete_dict_types(self, ids: list[int]) -> None:
        statement_data = text("DELETE FROM sys_dict_data WHERE dict_type_id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        )
        statement_types = text("DELETE FROM sys_dict_type WHERE id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        )
        await self.execute(statement_data, {"ids": ids})
        await self.execute(statement_types, {"ids": ids})

    async def page_dict_data(
        self,
        *,
        dict_type_id: int | None,
        dict_label: str | None,
        dict_value: str | None,
        page: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        params = {
            "type_id": dict_type_id,
            "dict_label": f"%{dict_label}%" if dict_label else None,
            "dict_value": f"%{dict_value}%" if dict_value else None,
            "offset": (page - 1) * limit,
            "limit": limit,
        }
        where = (
            "d.dict_type_id = :type_id AND (:dict_label IS NULL OR d.dict_label LIKE :dict_label) "
            "AND (:dict_value IS NULL OR d.dict_value LIKE :dict_value)"
        )
        total = int(await self.scalar(f"SELECT COUNT(*) FROM sys_dict_data d WHERE {where}", params) or 0)  # noqa: S608
        rows = await self.fetch_all(
            "SELECT d.id, d.dict_type_id, d.dict_label, d.dict_value, d.remark, d.sort, d.creator, "  # noqa: S608
            "d.create_date, d.updater, d.update_date, creator.username AS creator_name, "
            "updater.username AS updater_name FROM sys_dict_data d "
            "LEFT JOIN sys_user creator ON creator.id = d.creator "
            "LEFT JOIN sys_user updater ON updater.id = d.updater "
            f"WHERE {where} ORDER BY d.sort ASC LIMIT :limit OFFSET :offset",  # noqa: S608
            params,
        )
        return rows, total

    async def get_dict_data(self, data_id: int) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT id, dict_type_id, dict_label, dict_value, remark, sort, creator, create_date, updater, update_date "
            "FROM sys_dict_data WHERE id = :id",
            {"id": data_id},
        )

    async def dict_data_label_exists(
        self,
        dict_type_id: int | None,
        compared_label: str | None,
        *,
        exclude_id: int | None = None,
    ) -> bool:
        count = await self.scalar(
            "SELECT COUNT(*) FROM sys_dict_data WHERE dict_type_id = :type_id AND dict_label = :label "
            "AND (:exclude_id IS NULL OR id <> :exclude_id)",
            {"type_id": dict_type_id, "label": compared_label, "exclude_id": exclude_id},
        )
        return int(count or 0) > 0

    async def dict_type_code(self, type_id: int | None) -> str | None:
        value = await self.scalar("SELECT dict_type FROM sys_dict_type WHERE id = :id", {"id": type_id})
        return None if value is None else str(value)

    async def insert_dict_data(
        self,
        *,
        data_id: int,
        dict_type_id: int | None,
        dict_label: str | None,
        dict_value: str | None,
        remark: str | None,
        sort: int | None,
        user_id: int,
        now: datetime,
    ) -> None:
        await self.execute(
            "INSERT INTO sys_dict_data "
            "(id, dict_type_id, dict_label, dict_value, remark, sort, creator, create_date, updater, update_date) "
            "VALUES (:id, :type_id, :label, :value, :remark, :sort, :user_id, :now, :user_id, :now)",
            {
                "id": data_id,
                "type_id": dict_type_id,
                "label": dict_label,
                "value": dict_value,
                "remark": remark,
                "sort": sort,
                "user_id": user_id,
                "now": now,
            },
        )

    async def update_dict_data(
        self,
        *,
        data_id: int | None,
        dict_type_id: int | None,
        dict_label: str | None,
        dict_value: str | None,
        remark: str | None,
        sort: int | None,
        user_id: int,
        now: datetime,
    ) -> int:
        return await self.execute(
            "UPDATE sys_dict_data SET "
            "dict_type_id = CASE WHEN :has_type_id = 1 THEN :type_id ELSE dict_type_id END, "
            "dict_label = CASE WHEN :has_label = 1 THEN :label ELSE dict_label END, "
            "dict_value = CASE WHEN :has_value = 1 THEN :value ELSE dict_value END, "
            "remark = CASE WHEN :has_remark = 1 THEN :remark ELSE remark END, "
            "sort = CASE WHEN :has_sort = 1 THEN :sort ELSE sort END, updater = :user_id, update_date = :now "
            "WHERE id = :id",
            {
                "id": data_id,
                "has_type_id": int(dict_type_id is not None),
                "type_id": dict_type_id,
                "has_label": int(dict_label is not None),
                "label": dict_label,
                "has_value": int(dict_value is not None),
                "value": dict_value,
                "has_remark": int(remark is not None),
                "remark": remark,
                "has_sort": int(sort is not None),
                "sort": sort,
                "user_id": user_id,
                "now": now,
            },
        )

    async def dict_type_codes_for_data_ids(self, ids: list[int]) -> list[str]:
        statement = text(
            "SELECT DISTINCT t.dict_type FROM sys_dict_type t JOIN sys_dict_data d ON d.dict_type_id = t.id "
            "WHERE d.id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        rows = await self.fetch_all(statement, {"ids": ids})
        return [str(row["dict_type"]) for row in rows]

    async def delete_dict_data(self, ids: list[int]) -> int:
        statement = text("DELETE FROM sys_dict_data WHERE id IN :ids").bindparams(bindparam("ids", expanding=True))
        return await self.execute(statement, {"ids": ids})

    async def dict_items(self, dict_type: str) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT d.dict_label AS name, d.dict_value AS `key` FROM sys_dict_data d "
            "LEFT JOIN sys_dict_type t ON d.dict_type_id = t.id "
            "WHERE t.dict_type = :dict_type ORDER BY d.sort ASC",
            {"dict_type": dict_type},
        )
