from __future__ import annotations

# All interpolated SQL fragments are selected from closed column/table allowlists.
# ruff: noqa: S608
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Repository

AGENT_COLUMNS = (
    "id",
    "user_id",
    "agent_code",
    "agent_name",
    "asr_model_id",
    "vad_model_id",
    "llm_model_id",
    "slm_model_id",
    "vllm_model_id",
    "tts_model_id",
    "tts_voice_id",
    "tts_language",
    "tts_volume",
    "tts_rate",
    "tts_pitch",
    "mem_model_id",
    "intent_model_id",
    "chat_history_conf",
    "system_prompt",
    "summary_memory",
    "lang_code",
    "language",
    "sort",
    "creator",
    "created_at",
    "updater",
    "updated_at",
)
AGENT_MUTABLE_COLUMNS = frozenset(AGENT_COLUMNS) - {"id", "user_id", "creator", "created_at"}
TEMPLATE_COLUMNS = (
    "id",
    "agent_code",
    "agent_name",
    "asr_model_id",
    "vad_model_id",
    "llm_model_id",
    "vllm_model_id",
    "tts_model_id",
    "tts_voice_id",
    "tts_language",
    "tts_volume",
    "tts_rate",
    "tts_pitch",
    "mem_model_id",
    "intent_model_id",
    "chat_history_conf",
    "system_prompt",
    "summary_memory",
    "lang_code",
    "language",
    "sort",
    "creator",
    "created_at",
    "updater",
    "updated_at",
)


class AgentRepository(Repository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    @property
    def is_sqlite(self) -> bool:
        bind = self.session.get_bind()
        return bool(bind is not None and bind.dialect.name == "sqlite")

    async def get_agent(self, agent_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
        suffix = "" if self.is_sqlite or not for_update else " FOR UPDATE"
        return await self.fetch_one(
            f"SELECT {', '.join(AGENT_COLUMNS)} FROM ai_agent WHERE id=:id{suffix}", {"id": agent_id}
        )

    async def check_agent_owner(self, agent_id: str, user_id: int, *, super_admin: bool) -> bool:
        if super_admin:
            return bool(await self.scalar("SELECT 1 FROM ai_agent WHERE id=:id LIMIT 1", {"id": agent_id}))
        return bool(
            await self.scalar(
                "SELECT 1 FROM ai_agent WHERE id=:id AND user_id=:user_id LIMIT 1",
                {"id": agent_id, "user_id": user_id},
            )
        )

    async def list_user_agents(self, user_id: int, keyword: str | None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"user_id": user_id}
        where = "a.user_id=:user_id"
        if keyword is not None and keyword.strip():
            params["keyword"] = f"%{keyword}%"
            where += (
                " AND (a.agent_name LIKE :keyword"
                " OR EXISTS (SELECT 1 FROM ai_device d0 WHERE d0.agent_id=a.id"
                " AND d0.user_id=:user_id AND d0.mac_address LIKE :keyword)"
                " OR EXISTS (SELECT 1 FROM ai_agent_tag_relation tr0"
                " JOIN ai_agent_tag t0 ON t0.id=tr0.tag_id"
                " WHERE tr0.agent_id=a.id AND t0.deleted=0 AND t0.tag_name LIKE :keyword))"
            )
        return await self.fetch_all(
            "SELECT a.*, mt.model_name AS tts_model_name, ml.model_name AS llm_model_name,"
            " mv.model_name AS vllm_model_name, COALESCE(tv.name, vc.name) AS tts_voice_name,"
            " (SELECT MAX(d.last_connected_at) FROM ai_device d WHERE d.agent_id=a.id) AS last_connected_at,"
            " (SELECT COUNT(*) FROM ai_device d WHERE d.agent_id=a.id) AS device_count"
            " FROM ai_agent a"
            " LEFT JOIN ai_model_config mt ON mt.id=a.tts_model_id"
            " LEFT JOIN ai_model_config ml ON ml.id=a.llm_model_id"
            " LEFT JOIN ai_model_config mv ON mv.id=a.vllm_model_id"
            " LEFT JOIN ai_tts_voice tv ON tv.id=a.tts_voice_id"
            " LEFT JOIN ai_voice_clone vc ON vc.id=a.tts_voice_id"
            f" WHERE {where} ORDER BY a.created_at DESC",
            params,
        )

    async def list_admin_agents(
        self, page: int, limit: int, order_field: str, ascending: bool
    ) -> tuple[list[dict[str, Any]], int]:
        allowed = {"agent_name", "created_at", "updated_at", "sort", "id"}
        selected = order_field if order_field in allowed else "agent_name"
        direction = "ASC" if ascending else "DESC"
        total = int(await self.scalar("SELECT COUNT(*) FROM ai_agent") or 0)
        query = (
            f"SELECT {', '.join(AGENT_COLUMNS)} FROM ai_agent "
            f"ORDER BY {selected} {direction} LIMIT :limit OFFSET :offset"
        )
        rows = await self.fetch_all(
            query,
            {"limit": limit, "offset": (page - 1) * limit},
        )
        return rows, total

    async def insert_agent(self, values: Mapping[str, Any]) -> int:
        columns = [column for column in AGENT_COLUMNS if column in values]
        placeholders = ", ".join(f":{column}" for column in columns)
        return await self.execute(
            f"INSERT INTO ai_agent ({', '.join(columns)}) VALUES ({placeholders})",
            {column: values[column] for column in columns},
        )

    async def update_agent(self, agent_id: str, values: Mapping[str, Any], *, include_null: bool = False) -> int:
        selected = {
            key: value
            for key, value in values.items()
            if key in AGENT_MUTABLE_COLUMNS and (include_null or value is not None)
        }
        if not selected:
            return 0
        assignments = ", ".join(f"{column}=:{column}" for column in selected)
        return await self.execute(
            f"UPDATE ai_agent SET {assignments} WHERE id=:agent_id",
            {**selected, "agent_id": agent_id},
        )

    async def get_agent_plugins(self, agent_id: str) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT m.id,m.agent_id,m.plugin_id,m.param_info,p.provider_code"
            " FROM ai_agent_plugin_mapping m LEFT JOIN ai_model_provider p ON p.id=m.plugin_id"
            " WHERE m.agent_id=:agent_id ORDER BY m.id ASC",
            {"agent_id": agent_id},
        )

    async def replace_plugins(self, agent_id: str, plugins: Sequence[Mapping[str, Any]]) -> None:
        existing = await self.fetch_all(
            "SELECT id,plugin_id FROM ai_agent_plugin_mapping WHERE agent_id=:agent_id",
            {"agent_id": agent_id},
        )
        by_plugin = {str(row["plugin_id"]): int(row["id"]) for row in existing}
        incoming = {str(item.get("plugin_id") or "") for item in plugins}
        remove_ids = [int(row["id"]) for row in existing if str(row["plugin_id"]) not in incoming]
        if remove_ids:
            statement = text("DELETE FROM ai_agent_plugin_mapping WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            )
            await self.execute(statement, {"ids": remove_ids})
        for item in plugins:
            plugin_id = str(item.get("plugin_id") or "")
            params = {"agent_id": agent_id, "plugin_id": plugin_id, "param_info": item.get("param_info") or "{}"}
            if plugin_id in by_plugin:
                await self.execute(
                    "UPDATE ai_agent_plugin_mapping SET param_info=:param_info WHERE id=:id",
                    {"id": by_plugin[plugin_id], **params},
                )
            else:
                await self.execute(
                    "INSERT INTO ai_agent_plugin_mapping (id,agent_id,plugin_id,param_info)"
                    " VALUES (:id,:agent_id,:plugin_id,:param_info)",
                    {"id": int(item["id"]), **params},
                )

    async def delete_plugins(self, agent_id: str) -> int:
        return await self.execute("DELETE FROM ai_agent_plugin_mapping WHERE agent_id=:id", {"id": agent_id})

    async def get_context_provider(self, agent_id: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT id,agent_id,context_providers,creator,created_at,updater,updated_at"
            " FROM ai_agent_context_provider WHERE agent_id=:id LIMIT 1",
            {"id": agent_id},
        )

    async def upsert_context_provider(self, agent_id: str, encoded: str, new_id: str) -> None:
        existing = await self.get_context_provider(agent_id)
        if existing:
            await self.execute(
                "UPDATE ai_agent_context_provider SET context_providers=:value WHERE id=:id",
                {"value": encoded, "id": existing["id"]},
            )
        else:
            await self.execute(
                "INSERT INTO ai_agent_context_provider (id,agent_id,context_providers)"
                " VALUES (:id,:agent_id,:value)",
                {"id": new_id, "agent_id": agent_id, "value": encoded},
            )

    async def get_correct_word_ids(self, agent_id: str) -> list[str]:
        rows = await self.fetch_all(
            "SELECT file_id FROM ai_agent_correct_word_mapping WHERE agent_id=:id", {"id": agent_id}
        )
        return [str(row["file_id"]) for row in rows]

    async def replace_correct_words(
        self, agent_id: str, file_ids: Sequence[str], user_id: int, now: datetime, ids: Sequence[str]
    ) -> None:
        await self.execute("DELETE FROM ai_agent_correct_word_mapping WHERE agent_id=:id", {"id": agent_id})
        await self.execute_many(
            "INSERT INTO ai_agent_correct_word_mapping"
            " (id,agent_id,file_id,creator,created_at,updater,updated_at)"
            " VALUES (:id,:agent_id,:file_id,:user_id,:now,:user_id,:now)",
            [
                {"id": mapping_id, "agent_id": agent_id, "file_id": file_id, "user_id": user_id, "now": now}
                for mapping_id, file_id in zip(ids, file_ids, strict=True)
            ],
        )

    async def get_agent_tags(self, agent_id: str) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT t.id,t.tag_name,t.sort,r.sort AS relation_sort"
            " FROM ai_agent_tag t JOIN ai_agent_tag_relation r ON t.id=r.tag_id"
            " WHERE r.agent_id=:id AND t.deleted=0 ORDER BY r.sort ASC,r.created_at ASC",
            {"id": agent_id},
        )

    async def get_tags_for_agents(self, agent_ids: Sequence[str]) -> list[dict[str, Any]]:
        if not agent_ids:
            return []
        statement = text(
            "SELECT t.id,t.tag_name,r.agent_id,r.sort AS relation_sort"
            " FROM ai_agent_tag t JOIN ai_agent_tag_relation r ON t.id=r.tag_id"
            " WHERE r.agent_id IN :ids AND t.deleted=0 ORDER BY r.sort ASC,r.created_at ASC"
        ).bindparams(bindparam("ids", expanding=True))
        return await self.fetch_all(statement, {"ids": list(agent_ids)})

    async def list_tags(self) -> list[dict[str, Any]]:
        return await self.fetch_all("SELECT id,tag_name,sort FROM ai_agent_tag WHERE deleted=0 ORDER BY sort ASC")

    async def get_tag(self, tag_id: str) -> dict[str, Any] | None:
        return await self.fetch_one("SELECT * FROM ai_agent_tag WHERE id=:id", {"id": tag_id})

    async def find_active_tag_by_name(self, tag_name: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT * FROM ai_agent_tag WHERE tag_name=:name AND deleted=0 LIMIT 1", {"name": tag_name}
        )

    async def find_any_tag_by_name(self, tag_name: str) -> dict[str, Any] | None:
        return await self.fetch_one("SELECT * FROM ai_agent_tag WHERE tag_name=:name LIMIT 1", {"name": tag_name})

    async def insert_tag(self, values: Mapping[str, Any]) -> int:
        return await self.execute(
            "INSERT INTO ai_agent_tag"
            " (id,tag_name,sort,deleted,creator,created_at,updater,updated_at)"
            " VALUES (:id,:tag_name,:sort,:deleted,:creator,:created_at,:updater,:updated_at)",
            values,
        )

    async def soft_delete_tag(self, tag_id: str, now: datetime) -> int:
        return await self.execute(
            "UPDATE ai_agent_tag SET deleted=1,updated_at=:now WHERE id=:id",
            {"id": tag_id, "now": now},
        )

    async def replace_tag_relations(self, agent_id: str, relations: Sequence[Mapping[str, Any]]) -> None:
        await self.execute("DELETE FROM ai_agent_tag_relation WHERE agent_id=:id", {"id": agent_id})
        await self.execute_many(
            "INSERT INTO ai_agent_tag_relation"
            " (id,agent_id,tag_id,sort,creator,created_at,updater,updated_at)"
            " VALUES (:id,:agent_id,:tag_id,:sort,:creator,:created_at,:updater,:updated_at)",
            relations,
        )

    async def get_model_config(self, model_id: str | None) -> dict[str, Any] | None:
        if not model_id:
            return None
        return await self.fetch_one("SELECT * FROM ai_model_config WHERE id=:id", {"id": model_id})

    async def get_default_llm_config(self) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT * FROM ai_model_config WHERE model_type='LLM' AND is_enabled=1"
            " ORDER BY is_default DESC,sort ASC LIMIT 1"
        )

    async def get_model_provider(self, provider_id: str) -> dict[str, Any] | None:
        return await self.fetch_one("SELECT * FROM ai_model_provider WHERE id=:id", {"id": provider_id})

    async def get_timbre(self, timbre_id: str | None) -> dict[str, Any] | None:
        if not timbre_id:
            return None
        row = await self.fetch_one("SELECT * FROM ai_tts_voice WHERE id=:id", {"id": timbre_id})
        if row is None:
            row = await self.fetch_one("SELECT * FROM ai_voice_clone WHERE id=:id", {"id": timbre_id})
        return row

    async def find_timbre_by_voice_code(self, model_id: str, voice_code: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT * FROM ai_tts_voice WHERE tts_model_id=:model_id AND tts_voice=:voice LIMIT 1",
            {"model_id": model_id, "voice": voice_code},
        )

    async def get_device_by_mac(self, mac_address: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT * FROM ai_device WHERE mac_address=:mac ORDER BY id DESC LIMIT 1", {"mac": mac_address}
        )

    async def get_agent_by_device_mac(self, mac_address: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            f"SELECT {', '.join('a.' + column for column in AGENT_COLUMNS)}"
            " FROM ai_device d LEFT JOIN ai_agent a ON d.agent_id=a.id"
            " WHERE d.mac_address=:mac ORDER BY d.id DESC LIMIT 1",
            {"mac": mac_address},
        )

    async def update_device_connection(self, device_id: str, now: datetime) -> int:
        return await self.execute(
            "UPDATE ai_device SET last_connected_at=:now WHERE id=:id", {"id": device_id, "now": now}
        )

    async def insert_chat_audio(self, audio_id: str, audio: bytes) -> int:
        return await self.execute(
            "INSERT INTO ai_agent_chat_audio (id,audio) VALUES (:id,:audio)", {"id": audio_id, "audio": audio}
        )

    async def get_chat_audio(self, audio_id: str) -> bytes | None:
        value = await self.scalar("SELECT audio FROM ai_agent_chat_audio WHERE id=:id", {"id": audio_id})
        return bytes(value) if value is not None else None

    async def insert_chat_history(self, values: Mapping[str, Any]) -> int:
        return await self.execute(
            "INSERT INTO ai_agent_chat_history"
            " (mac_address,agent_id,session_id,chat_type,content,audio_id,created_at)"
            " VALUES (:mac_address,:agent_id,:session_id,:chat_type,:content,:audio_id,:created_at)",
            values,
        )

    async def get_session_agent_id(self, session_id: str) -> str | None:
        value = await self.scalar(
            "SELECT agent_id FROM ai_agent_chat_history WHERE session_id=:id LIMIT 1", {"id": session_id}
        )
        return str(value) if value is not None else None

    async def get_audio_agent_id(self, audio_id: str) -> str | None:
        value = await self.scalar(
            "SELECT agent_id FROM ai_agent_chat_history WHERE audio_id=:id LIMIT 1", {"id": audio_id}
        )
        return str(value) if value is not None else None

    async def is_audio_owned(self, audio_id: str, agent_id: str) -> bool:
        count = await self.scalar(
            "SELECT COUNT(*) FROM ai_agent_chat_history WHERE audio_id=:audio_id AND agent_id=:agent_id",
            {"audio_id": audio_id, "agent_id": agent_id},
        )
        return int(count or 0) == 1

    async def get_audio_content(self, audio_id: str) -> str | None:
        value = await self.scalar(
            "SELECT content FROM ai_agent_chat_history WHERE audio_id=:id LIMIT 1", {"id": audio_id}
        )
        return str(value) if value is not None else None

    async def get_chat_history(self, agent_id: str, session_id: str) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT created_at,chat_type,content,audio_id,mac_address"
            " FROM ai_agent_chat_history WHERE agent_id=:agent_id AND session_id=:session_id"
            " ORDER BY created_at ASC",
            {"agent_id": agent_id, "session_id": session_id},
        )

    async def get_recent_user_history(self, agent_id: str) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT content,audio_id FROM ai_agent_chat_history"
            " WHERE agent_id=:id AND chat_type=1 AND audio_id IS NOT NULL ORDER BY id DESC LIMIT 50",
            {"id": agent_id},
        )

    async def list_sessions(self, agent_id: str, page: int, limit: int) -> tuple[list[dict[str, Any]], int]:
        total = int(
            await self.scalar(
                "SELECT COUNT(*) FROM (SELECT session_id FROM ai_agent_chat_history"
                " WHERE agent_id=:id GROUP BY session_id) sessions",
                {"id": agent_id},
            )
            or 0
        )
        rows = await self.fetch_all(
            "SELECT h.session_id,MAX(h.created_at) AS created_at,COUNT(*) AS chat_count,"
            " (SELECT t.title FROM ai_agent_chat_title t WHERE t.session_id=h.session_id LIMIT 1) AS title"
            " FROM ai_agent_chat_history h WHERE h.agent_id=:id GROUP BY h.session_id"
            " ORDER BY created_at DESC LIMIT :limit OFFSET :offset",
            {"id": agent_id, "limit": limit, "offset": (page - 1) * limit},
        )
        return rows, total

    async def upsert_chat_title(self, session_id: str, title: str, now: datetime, title_id: str) -> None:
        existing = await self.fetch_one(
            "SELECT id FROM ai_agent_chat_title WHERE session_id=:session_id LIMIT 1", {"session_id": session_id}
        )
        if existing:
            await self.execute(
                "UPDATE ai_agent_chat_title SET title=:title,updated_at=:now WHERE id=:id",
                {"id": existing["id"], "title": title, "now": now},
            )
        else:
            await self.execute(
                "INSERT INTO ai_agent_chat_title (id,session_id,title,created_at,updated_at)"
                " VALUES (:id,:session_id,:title,:now,:now)",
                {"id": title_id, "session_id": session_id, "title": title, "now": now},
            )

    async def delete_chat_history(self, agent_id: str, *, delete_audio: bool, delete_text: bool) -> None:
        if delete_audio:
            ids = await self.fetch_all(
                "SELECT DISTINCT audio_id FROM ai_agent_chat_history WHERE agent_id=:id AND audio_id IS NOT NULL",
                {"id": agent_id},
            )
            audio_ids = [str(row["audio_id"]) for row in ids]
            for offset in range(0, len(audio_ids), 1000):
                batch = audio_ids[offset : offset + 1000]
                statement = text("DELETE FROM ai_agent_chat_audio WHERE id IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                )
                await self.execute(statement, {"ids": batch})
        if delete_audio and not delete_text:
            await self.execute("UPDATE ai_agent_chat_history SET audio_id=NULL WHERE agent_id=:id", {"id": agent_id})
        if delete_text:
            await self.execute("DELETE FROM ai_agent_chat_history WHERE agent_id=:id", {"id": agent_id})

    async def delete_agent_cascade(self, agent_id: str) -> None:
        devices = await self.fetch_all("SELECT mac_address FROM ai_device WHERE agent_id=:id", {"id": agent_id})
        macs = [str(row["mac_address"]) for row in devices if row.get("mac_address") is not None]
        await self.execute("DELETE FROM ai_device WHERE agent_id=:id", {"id": agent_id})
        if macs:
            statement = text(
                "DELETE FROM ai_device_address_book WHERE mac_address IN :macs OR target_mac IN :targets"
            ).bindparams(bindparam("macs", expanding=True), bindparam("targets", expanding=True))
            await self.execute(statement, {"macs": macs, "targets": macs})
        await self.delete_chat_history(agent_id, delete_audio=True, delete_text=True)
        for table in (
            "ai_agent_plugin_mapping",
            "ai_agent_context_provider",
            "ai_agent_correct_word_mapping",
            "ai_agent_tag_relation",
            "ai_agent_snapshot",
        ):
            await self.execute(f"DELETE FROM {table} WHERE agent_id=:id", {"id": agent_id})
        await self.execute("DELETE FROM ai_agent WHERE id=:id", {"id": agent_id})

    async def list_templates(
        self, *, name: str | None = None, page: int | None = None, limit: int | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        params: dict[str, Any] = {}
        where = ""
        if name:
            where = " WHERE agent_name LIKE :name"
            params["name"] = f"%{name}%"
        total = int(await self.scalar(f"SELECT COUNT(*) FROM ai_agent_template{where}", params) or 0)
        paging = ""
        if page is not None and limit is not None:
            params.update(limit=limit, offset=(page - 1) * limit)
            paging = " LIMIT :limit OFFSET :offset"
        rows = await self.fetch_all(f"SELECT * FROM ai_agent_template{where} ORDER BY sort ASC{paging}", params)
        return rows, total

    async def get_template(self, template_id: str) -> dict[str, Any] | None:
        return await self.fetch_one("SELECT * FROM ai_agent_template WHERE id=:id", {"id": template_id})

    async def get_default_template(self) -> dict[str, Any] | None:
        return await self.fetch_one("SELECT * FROM ai_agent_template ORDER BY sort ASC LIMIT 1")

    async def next_template_sort(self) -> int:
        rows = await self.fetch_all("SELECT sort FROM ai_agent_template WHERE sort IS NOT NULL ORDER BY sort ASC")
        expected = 1
        for row in rows:
            value = int(row["sort"])
            if value > expected:
                return expected
            expected = value + 1
        return expected

    async def insert_template(self, values: Mapping[str, Any]) -> int:
        columns = [column for column in TEMPLATE_COLUMNS if column in values]
        return await self.execute(
            f"INSERT INTO ai_agent_template ({', '.join(columns)})"
            f" VALUES ({', '.join(':' + column for column in columns)})",
            {column: values[column] for column in columns},
        )

    async def update_template(self, template_id: str, values: Mapping[str, Any]) -> int:
        selected = {
            key: value for key, value in values.items() if key in TEMPLATE_COLUMNS and key != "id" and value is not None
        }
        if not selected:
            return 0
        return await self.execute(
            f"UPDATE ai_agent_template SET {', '.join(key + '=:' + key for key in selected)} WHERE id=:id",
            {**selected, "id": template_id},
        )

    async def delete_template(self, template_id: str) -> int:
        return await self.execute("DELETE FROM ai_agent_template WHERE id=:id", {"id": template_id})

    async def reorder_templates(self, deleted_sort: int) -> int:
        return await self.execute("UPDATE ai_agent_template SET sort=sort-1 WHERE sort>:sort", {"sort": deleted_sort})

    async def delete_templates(self, ids: Sequence[str]) -> int:
        if not ids:
            return 0
        statement = text("DELETE FROM ai_agent_template WHERE id IN :ids").bindparams(bindparam("ids", expanding=True))
        return await self.execute(statement, {"ids": list(ids)})

    async def list_voiceprints(self, agent_id: str, user_id: int) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT id,audio_id,source_name,introduce,create_date"
            " FROM ai_agent_voice_print WHERE agent_id=:agent_id AND creator=:user_id",
            {"agent_id": agent_id, "user_id": user_id},
        )

    async def list_voiceprint_ids(self, agent_id: str) -> list[str]:
        rows = await self.fetch_all("SELECT id FROM ai_agent_voice_print WHERE agent_id=:id", {"id": agent_id})
        return [str(row["id"]) for row in rows]

    async def get_voiceprint(self, voiceprint_id: str, user_id: int | None = None) -> dict[str, Any] | None:
        where = "id=:id"
        params: dict[str, Any] = {"id": voiceprint_id}
        if user_id is not None:
            where += " AND creator=:user_id"
            params["user_id"] = user_id
        return await self.fetch_one(f"SELECT * FROM ai_agent_voice_print WHERE {where} LIMIT 1", params)

    async def insert_voiceprint(self, values: Mapping[str, Any]) -> int:
        return await self.execute(
            "INSERT INTO ai_agent_voice_print"
            " (id,agent_id,audio_id,source_name,introduce,creator,create_date,updater,update_date)"
            " VALUES (:id,:agent_id,:audio_id,:source_name,:introduce,:creator,:create_date,:updater,:update_date)",
            values,
        )

    async def update_voiceprint(self, voiceprint_id: str, user_id: int, values: Mapping[str, Any]) -> int:
        allowed = {"audio_id", "source_name", "introduce", "updater", "update_date"}
        selected = {key: value for key, value in values.items() if key in allowed and value is not None}
        if not selected:
            return 0
        return await self.execute(
            f"UPDATE ai_agent_voice_print SET {', '.join(key + '=:' + key for key in selected)}"
            " WHERE id=:id AND creator=:user_id",
            {**selected, "id": voiceprint_id, "user_id": user_id},
        )

    async def delete_voiceprint(self, voiceprint_id: str, user_id: int) -> int:
        return await self.execute(
            "DELETE FROM ai_agent_voice_print WHERE id=:id AND creator=:user_id",
            {"id": voiceprint_id, "user_id": user_id},
        )

    async def snapshot_max_version(self, agent_id: str) -> int:
        return int(
            await self.scalar(
                "SELECT COALESCE(MAX(version_no),0) FROM ai_agent_snapshot WHERE agent_id=:id", {"id": agent_id}
            )
            or 0
        )

    async def latest_snapshot(self, agent_id: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT * FROM ai_agent_snapshot WHERE agent_id=:id ORDER BY version_no DESC LIMIT 1", {"id": agent_id}
        )

    async def next_snapshot(self, agent_id: str, version_no: int) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT * FROM ai_agent_snapshot WHERE agent_id=:id AND version_no>:version"
            " ORDER BY version_no ASC LIMIT 1",
            {"id": agent_id, "version": version_no},
        )

    async def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        return await self.fetch_one("SELECT * FROM ai_agent_snapshot WHERE id=:id", {"id": snapshot_id})

    async def list_snapshots(
        self, agent_id: str, page: int, limit: int, max_version_no: int | None
    ) -> tuple[list[dict[str, Any]], int]:
        params: dict[str, Any] = {"id": agent_id, "limit": limit, "offset": (page - 1) * limit}
        extra = ""
        if max_version_no is not None:
            extra = " AND version_no<=:max_version"
            params["max_version"] = max_version_no
        total = int(await self.scalar(f"SELECT COUNT(*) FROM ai_agent_snapshot WHERE agent_id=:id{extra}", params) or 0)
        rows = await self.fetch_all(
            f"SELECT * FROM ai_agent_snapshot WHERE agent_id=:id{extra}"
            " ORDER BY version_no DESC LIMIT :limit OFFSET :offset",
            params,
        )
        return rows, total

    async def insert_snapshot_next_version(self, values: Mapping[str, Any]) -> int:
        return await self.execute(
            "INSERT INTO ai_agent_snapshot"
            " (id,agent_id,user_id,version_no,snapshot_data,changed_fields,source,"
            " restore_from_snapshot_id,restore_from_version_no,creator,created_at,redaction_version)"
            " SELECT :id,:agent_id,:user_id,COALESCE(MAX(version_no),0)+1,:snapshot_data,:changed_fields,:source,"
            " :restore_from_snapshot_id,:restore_from_version_no,:creator,:created_at,:redaction_version"
            " FROM ai_agent_snapshot WHERE agent_id=:agent_id",
            values,
        )

    async def prune_snapshots(self, agent_id: str, keep: int) -> int:
        rows = await self.fetch_all(
            "SELECT id FROM ai_agent_snapshot WHERE agent_id=:id ORDER BY version_no DESC LIMIT :keep",
            {"id": agent_id, "keep": keep},
        )
        retained = [str(row["id"]) for row in rows]
        if not retained:
            return 0
        statement = text("DELETE FROM ai_agent_snapshot WHERE agent_id=:agent_id AND id NOT IN :retained").bindparams(
            bindparam("retained", expanding=True)
        )
        return await self.execute(statement, {"agent_id": agent_id, "retained": retained})

    async def delete_snapshot(self, snapshot_id: str) -> int:
        return await self.execute("DELETE FROM ai_agent_snapshot WHERE id=:id", {"id": snapshot_id})

    async def list_legacy_snapshots(self, after_id: str | None, limit: int, version: int) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"version": version, "limit": limit}
        extra = ""
        if after_id is not None:
            extra = " AND id>:after_id"
            params["after_id"] = after_id
        return await self.fetch_all(
            f"SELECT id,snapshot_data,redaction_version FROM ai_agent_snapshot"
            f" WHERE redaction_version<:version{extra} ORDER BY id ASC LIMIT :limit",
            params,
        )

    async def update_redacted_snapshot(self, snapshot_id: str, snapshot_data: str, version: int) -> int:
        return await self.execute(
            "UPDATE ai_agent_snapshot SET snapshot_data=:data,redaction_version=:version"
            " WHERE id=:id AND redaction_version<:version",
            {"id": snapshot_id, "data": snapshot_data, "version": version},
        )
