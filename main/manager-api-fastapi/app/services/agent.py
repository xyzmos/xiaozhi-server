from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
import logging
import re
import time
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, NoReturn
from urllib.parse import unquote_plus, urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.errors import AppError
from app.core.i18n import message_for
from app.core.ids import snowflake
from app.core.redis import distributed_lock, java_get, java_set
from app.core.security import AuthUser, shanghai_now_naive
from app.integrations.llm import SUMMARY_PROMPT, TITLE_PROMPT, openai_completion
from app.integrations.mcp import build_agent_mcp_address, list_mcp_tools
from app.integrations.voiceprint import VoicePrintClient, VoicePrintIntegrationError
from app.repositories.agent import AgentRepository
from app.schemas.agent import (
    SNAPSHOT_FIELD_ORDER,
    AgentChatHistoryReport,
    AgentCreate,
    AgentMemory,
    AgentSnapshotData,
    AgentSnapshotPage,
    AgentTemplate,
    AgentUpdate,
    AgentVoicePrintSave,
    AgentVoicePrintUpdate,
)
from app.services.system_params import SystemParamService

logger = logging.getLogger(__name__)

MEMORY_NO_MEM = "Memory_nomem"
MEMORY_REPORT_ONLY = "Memory_mem_report_only"
MEMORY_MEM0AI = "Memory_mem0ai"
MEMORY_POWERMEM = "Memory_powermem"
SECRET_PLACEHOLDER = "__SNAPSHOT_SECRET_REDACTED__"  # noqa: S105 - marker, not a credential
CURRENT_REDACTION_VERSION = 2
MAX_SNAPSHOTS_PER_AGENT = 100
LEGACY_REDACTION_BATCH_SIZE = 100

ERROR_AGENT_NOT_FOUND = 10053
ERROR_VOICEPRINT_NOT_CONFIGURED = 10054
ERROR_VOICEPRINT_CREATE_FAILED = 10057
ERROR_VOICEPRINT_UPDATE_FAILED = 10058
ERROR_VOICEPRINT_DELETE_FAILED = 10059
ERROR_LLM_INTENT_MISMATCH = 10079
ERROR_NO_PERMISSION = 10169
ERROR_TAG_DUPLICATE = 10196
ERROR_TAG_EMPTY = 10197

_DEVICE_CONTROL = re.compile("设备控制|设备操作|控制设备|设备状态", re.IGNORECASE)
_WEATHER = re.compile("天气|温度|湿度|降雨|气象", re.IGNORECASE)
_DATE_WORDS = re.compile("日期|时间|星期|月份|年份", re.IGNORECASE)
_TITLE_PUNCTUATION = re.compile("[，。！？、：；''\"“”【】（）]")


def _uuid32() -> str:
    return uuid.uuid4().hex


def _json_load(value: Any, default: Any) -> Any:
    if value is None:
        return copy.deepcopy(default)
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        if not value.strip():
            return copy.deepcopy(default)
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return copy.deepcopy(default)
    return copy.deepcopy(value)


def _json_dump(value: Any, *, sort_keys: bool = False) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=sort_keys)


def _as_api_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return dict(row)


def _first_language(value: Any) -> str | None:
    if value is None:
        return None
    for item in re.split(r"[、；;,，]", str(value)):
        if item.strip():
            return item.strip()
    return None


def _cached_datetime(value: Any) -> datetime | None:
    timezone = ZoneInfo(get_settings().timezone)
    if isinstance(value, datetime):
        return value.astimezone(timezone).replace(tzinfo=None) if value.tzinfo is not None else value
    if (
        isinstance(value, list)
        and len(value) == 2
        and value[0] == "java.util.Date"
        and isinstance(value[1], int | float)
    ):
        return datetime.fromtimestamp(float(value[1]) / 1000, timezone).replace(tzinfo=None)
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return None


class AgentService:
    def __init__(self, session: AsyncSession, user: AuthUser | None = None, *, language: str | None = None):
        self.session = session
        self.repo = AgentRepository(session)
        self.user = user
        self.language = language

    @property
    def actor_id(self) -> int:
        return self.user.id if self.user is not None else 0

    async def _rollback_and_raise(self, exception: Exception) -> NoReturn:
        await self.session.rollback()
        raise exception

    async def require_agent(
        self, agent_id: str, *, permission: bool = True, for_update: bool = False
    ) -> dict[str, Any]:
        row = await self.repo.get_agent(agent_id, for_update=for_update)
        if row is None:
            raise AppError(ERROR_AGENT_NOT_FOUND)
        if (
            permission
            and self.user is not None
            and not self.user.is_super_admin
            and int(row.get("user_id") or 0) != self.user.id
        ):
            raise AppError(ERROR_NO_PERMISSION)
        return row

    async def has_agent_permission(self, agent_id: str) -> bool:
        if self.user is None:
            return False
        return await self.repo.check_agent_owner(agent_id, self.user.id, super_admin=self.user.is_super_admin)

    async def require_agent_permission(self, agent_id: str) -> None:
        """Mirror AgentController.requireAgentPermission before loading a record."""
        if not await self.has_agent_permission(agent_id):
            raise AppError(ERROR_NO_PERMISSION)

    async def require_snapshot_permission(self, agent_id: str) -> None:
        """SnapshotController uses a domain-specific, non-i18n permission error."""
        if not await self.has_agent_permission(agent_id):
            raise AppError(500, "没有权限访问该智能体快照")

    async def user_agents(self, keyword: str | None) -> list[dict[str, Any]]:
        if self.user is None:
            raise AppError(401)
        rows = await self.repo.list_user_agents(self.user.id, keyword)
        tags = await self.repo.get_tags_for_agents([str(row["id"]) for row in rows])
        tags_by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for tag in tags:
            tags_by_agent[str(tag["agent_id"])].append({"id": tag["id"], "tagName": tag["tag_name"]})
        result: list[dict[str, Any]] = []
        for row in rows:
            agent_id = str(row["id"])
            device_count = int(row.get("device_count") or 0)
            last_connected_at = row.get("last_connected_at")
            cached_count = await java_get(f"agent:device:count:{agent_id}")
            if isinstance(cached_count, int) and not isinstance(cached_count, bool):
                device_count = cached_count
            else:
                await java_set(f"agent:device:count:{agent_id}", device_count, 60)
            cached_last_connected = _cached_datetime(
                await java_get(f"agent:device:lastConnected:{agent_id}")
            )
            if cached_last_connected is not None:
                last_connected_at = cached_last_connected
            elif isinstance(last_connected_at, datetime):
                await java_set(
                    f"agent:device:lastConnected:{agent_id}",
                    last_connected_at,
                    86400,
                )
            voice_name = row.get("tts_voice_name")
            if (
                voice_name
                and row.get("tts_voice_id")
                and not await self.repo.scalar("SELECT 1 FROM ai_tts_voice WHERE id=:id", {"id": row["tts_voice_id"]})
            ):
                voice_name = f"{message_for(10158, self.language)}{voice_name}"
            result.append(
                {
                    "id": row["id"],
                    "agentName": row.get("agent_name"),
                    "ttsModelName": row.get("tts_model_name"),
                    "ttsVoiceName": voice_name,
                    "llmModelName": row.get("llm_model_name"),
                    "vllmModelName": row.get("vllm_model_name"),
                    "memModelId": row.get("mem_model_id"),
                    "systemPrompt": row.get("system_prompt"),
                    "summaryMemory": None,
                    "lastConnectedAt": last_connected_at,
                    "deviceCount": device_count,
                    "tags": tags_by_agent.get(str(row["id"])) or None,
                }
            )
        return result

    async def admin_agents(self, page: int, limit: int, order_field: str | None, order: str | None) -> dict[str, Any]:
        rows, total = await self.repo.list_admin_agents(
            page, limit, order_field or "agent_name", (order or "asc").lower() == "asc"
        )
        return {"list": [_as_api_row(row) for row in rows], "total": total}

    async def agent_detail(self, agent_id: str, *, permission: bool = True) -> dict[str, Any]:
        agent = await self.require_agent(agent_id, permission=permission)
        result = _as_api_row(agent)
        if result.get("mem_model_id") == MEMORY_NO_MEM:
            result["chat_history_conf"] = 0
        elif result.get("chat_history_conf") is None:
            result["chat_history_conf"] = 2
        plugins = await self.repo.get_agent_plugins(agent_id)
        result["functions"] = [
            {
                "id": row["id"],
                "agent_id": row["agent_id"],
                "plugin_id": row["plugin_id"],
                "param_info": row.get("param_info"),
            }
            for row in plugins
        ]
        context = await self.repo.get_context_provider(agent_id)
        result["context_providers"] = _json_load(context.get("context_providers") if context else None, [])
        result["correct_word_file_ids"] = await self.repo.get_correct_word_ids(agent_id)
        result["current_version_no"] = await self.repo.snapshot_max_version(agent_id)
        return result

    async def create_agent(self, dto: AgentCreate) -> str:
        now = shanghai_now_naive()
        agent_id = _uuid32()
        values: dict[str, Any] = {
            "id": agent_id,
            "user_id": self.actor_id,
            "agent_code": f"AGT_{int(time.time() * 1000)}",
            "agent_name": dto.agent_name,
            "sort": 0,
            "creator": self.actor_id,
            "created_at": now,
        }
        try:
            template = await self.repo.get_default_template()
            if template:
                for column in (
                    "asr_model_id",
                    "vad_model_id",
                    "llm_model_id",
                    "vllm_model_id",
                    "tts_model_id",
                    "tts_voice_id",
                    "mem_model_id",
                    "intent_model_id",
                    "system_prompt",
                    "summary_memory",
                    "lang_code",
                    "language",
                ):
                    values[column] = template.get(column)
                if values.get("tts_voice_id") is None and values.get("tts_model_id"):
                    model = await self.repo.get_model_config(str(values["tts_model_id"]))
                    config = _json_load(model.get("config_json") if model else None, {})
                    voice = config.get("voice") or config.get("speaker")
                    if voice:
                        timbre = await self.repo.find_timbre_by_voice_code(str(values["tts_model_id"]), str(voice))
                        if timbre:
                            values["tts_voice_id"] = timbre["id"]
                timbre = await self.repo.get_timbre(str(values["tts_voice_id"]) if values.get("tts_voice_id") else None)
                values["tts_language"] = template.get("tts_language") or _first_language(
                    timbre.get("languages") if timbre else None
                )
                if values.get("mem_model_id") in {MEMORY_NO_MEM, MEMORY_REPORT_ONLY}:
                    values["summary_memory"] = ""
                values["chat_history_conf"] = (
                    0
                    if values.get("mem_model_id") == MEMORY_NO_MEM
                    else 2
                    if values.get("mem_model_id") is not None
                    else template.get("chat_history_conf")
                )
            default_llm = await self.repo.get_default_llm_config()
            values["slm_model_id"] = default_llm.get("id") if default_llm else None
            await self.repo.insert_agent(values)
            default_plugins: list[dict[str, Any]] = []
            for plugin_id in ("SYSTEM_PLUGIN_MUSIC", "SYSTEM_PLUGIN_WEATHER", "SYSTEM_PLUGIN_NEWS_NEWSNOW"):
                provider = await self.repo.get_model_provider(plugin_id)
                if provider is None:
                    continue
                param_info: dict[str, Any] = {}
                for field in _json_load(provider.get("fields"), []):
                    if isinstance(field, dict) and field.get("key") is not None:
                        param_info[str(field["key"])] = field.get("default")
                default_plugins.append(
                    {
                        "id": snowflake.next_id(),
                        "plugin_id": plugin_id,
                        "param_info": _json_dump(param_info),
                    }
                )
            await self.repo.replace_plugins(agent_id, default_plugins)
            await self._create_snapshot(agent_id, "initial")
            await self.session.commit()
            return agent_id
        except Exception as exc:
            await self._rollback_and_raise(exc)

    async def update_agent(
        self,
        agent_id: str,
        dto: AgentUpdate,
        *,
        check_permission: bool = True,
        create_snapshot: bool = True,
    ) -> None:
        try:
            agent = await self.require_agent(agent_id, permission=check_permission, for_update=True)
            if create_snapshot:
                version = await self.repo.snapshot_max_version(agent_id)
                await self._create_snapshot(agent_id, "initial" if version == 0 else "current")
            payload = dto.model_dump(by_alias=False)
            scalar_columns = {
                key: value
                for key, value in payload.items()
                if key
                in {
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
                    "system_prompt",
                    "summary_memory",
                    "chat_history_conf",
                    "lang_code",
                    "language",
                    "sort",
                }
                and value is not None
            }
            effective = {**agent, **scalar_columns}
            now = shanghai_now_naive()
            if dto.functions is not None:
                await self.repo.replace_plugins(
                    agent_id,
                    [
                        {
                            "id": snowflake.next_id(),
                            "plugin_id": item.plugin_id or "",
                            "param_info": _json_dump(item.param_info),
                        }
                        for item in dto.functions
                    ],
                )
            if effective.get("mem_model_id") == MEMORY_NO_MEM:
                await self.repo.delete_chat_history(agent_id, delete_audio=True, delete_text=True)
                scalar_columns["summary_memory"] = ""
                effective["summary_memory"] = ""
            elif effective.get("mem_model_id") == MEMORY_REPORT_ONLY:
                scalar_columns["summary_memory"] = ""
                effective["summary_memory"] = ""
            if dto.context_providers is not None:
                await self.repo.upsert_context_provider(
                    agent_id,
                    _json_dump([item.model_dump(by_alias=True) for item in dto.context_providers]),
                    _uuid32(),
                )
            if dto.correct_word_file_ids is not None:
                await self.repo.replace_correct_words(
                    agent_id,
                    dto.correct_word_file_ids,
                    self.actor_id,
                    now,
                    [_uuid32() for _ in dto.correct_word_file_ids],
                )
            if dto.tag_names is not None or dto.tag_ids is not None:
                await self._replace_agent_tags(agent_id, dto.tag_ids, dto.tag_names)
            await self._validate_llm_intent(effective.get("llm_model_id"), effective.get("intent_model_id"))
            scalar_columns.update(updater=self.actor_id, updated_at=now)
            await self.repo.update_agent(agent_id, scalar_columns)
            if create_snapshot:
                await self._create_snapshot(agent_id, "config")
            await self.session.commit()
        except Exception as exc:
            await self._rollback_and_raise(exc)

    async def update_memory_by_mac(self, mac_address: str, dto: AgentMemory) -> None:
        device = await self.repo.get_device_by_mac(mac_address)
        if device is None or not device.get("agent_id"):
            return
        if self.user is not None and not self.user.is_super_admin and int(device.get("user_id") or 0) != self.user.id:
            raise AppError(ERROR_NO_PERMISSION)
        await self.update_agent(
            str(device["agent_id"]),
            AgentUpdate(summary_memory=dto.summary_memory),
            check_permission=False,
            create_snapshot=False,
        )

    async def delete_agent(self, agent_id: str) -> None:
        try:
            await self.require_agent(agent_id, permission=True, for_update=True)
            await self.repo.delete_agent_cascade(agent_id)
            await self.session.commit()
        except Exception as exc:
            await self._rollback_and_raise(exc)

    async def _validate_llm_intent(self, llm_model_id: Any, intent_model_id: Any) -> None:
        if not llm_model_id:
            return
        model = await self.repo.get_model_config(str(llm_model_id))
        config = _json_load(model.get("config_json") if model else None, {})
        model_type = str(config.get("type") or "")
        if (
            model is None
            or not config
            or (model_type not in {"openai", "ollama"} and intent_model_id == "Intent_function_call")
        ):
            raise AppError(ERROR_LLM_INTENT_MISMATCH)

    async def save_tag(self, tag_name: str) -> dict[str, Any]:
        if not tag_name.strip():
            raise AppError(ERROR_TAG_EMPTY)
        existing = await self.repo.find_active_tag_by_name(tag_name)
        if existing is not None:
            return _as_api_row(existing)
        now = shanghai_now_naive()
        values = {
            "id": _uuid32(),
            "tag_name": tag_name,
            "sort": 0,
            "deleted": 0,
            "creator": None,
            "created_at": now,
            "updater": None,
            "updated_at": now,
        }
        try:
            await self.repo.insert_tag(values)
            await self.session.commit()
            return values
        except Exception as exc:
            await self._rollback_and_raise(exc)

    async def delete_tag(self, tag_id: str) -> None:
        try:
            await self.repo.soft_delete_tag(tag_id, shanghai_now_naive())
            await self.session.commit()
        except Exception as exc:
            await self._rollback_and_raise(exc)

    async def all_tags(self) -> list[dict[str, Any]]:
        return [{"id": row["id"], "tagName": row["tag_name"]} for row in await self.repo.list_tags()]

    async def agent_tags(self, agent_id: str) -> list[dict[str, Any]]:
        await self.require_agent_permission(agent_id)
        return [{"id": row["id"], "tagName": row["tag_name"]} for row in await self.repo.get_agent_tags(agent_id)]

    async def save_agent_tags(self, agent_id: str, tag_ids: list[str] | None, tag_names: list[str] | None) -> None:
        await self.require_agent_permission(agent_id)
        await self.update_agent(agent_id, AgentUpdate(tag_ids=tag_ids, tag_names=tag_names))

    async def _replace_agent_tags(
        self, agent_id: str, tag_ids: Sequence[str] | None, tag_names: Sequence[str] | None
    ) -> None:
        new_names: list[str] = []
        seen: set[str] = set()
        for name in tag_names or []:
            if not name.strip():
                raise AppError(ERROR_TAG_EMPTY)
            if name in seen:
                raise AppError(ERROR_TAG_DUPLICATE)
            seen.add(name)
            new_names.append(name)
        all_ids: list[str] = []
        now = shanghai_now_naive()
        for name in new_names:
            tag = await self.repo.find_active_tag_by_name(name)
            if tag is None:
                values = {
                    "id": _uuid32(),
                    "tag_name": name,
                    "sort": 0,
                    "deleted": 0,
                    "creator": None,
                    "created_at": now,
                    "updater": None,
                    "updated_at": now,
                }
                await self.repo.insert_tag(values)
                all_ids.append(str(values["id"]))
            else:
                all_ids.append(str(tag["id"]))
        selected_rows = [await self.repo.get_tag(tag_id) for tag_id in tag_ids or []]
        selected_names = {str(row["tag_name"]) for row in selected_rows if row is not None}
        if selected_names.intersection(new_names):
            raise AppError(ERROR_TAG_DUPLICATE)
        all_ids.extend(tag_ids or [])
        relations = [
            {
                "id": _uuid32(),
                "agent_id": agent_id,
                "tag_id": tag_id,
                "sort": index,
                "creator": None,
                "created_at": now,
                "updater": None,
                "updated_at": now,
            }
            for index, tag_id in enumerate(all_ids)
        ]
        await self.repo.replace_tag_relations(agent_id, relations)

    async def templates(self) -> list[dict[str, Any]]:
        rows, _ = await self.repo.list_templates()
        return [_as_api_row(row) for row in rows]

    async def template_page(self, page: int, limit: int, agent_name: str | None) -> dict[str, Any]:
        rows, total = await self.repo.list_templates(name=agent_name, page=page, limit=limit)
        # The Java controller declares model-name fields but never populates them.
        return {"list": [{**row, "ttsModelName": None, "llmModelName": None} for row in rows], "total": total}

    async def template_detail(self, template_id: str) -> dict[str, Any] | None:
        row = await self.repo.get_template(template_id)
        return None if row is None else {**row, "ttsModelName": None, "llmModelName": None}

    async def create_template(self, template: AgentTemplate) -> dict[str, Any]:
        values = template.model_dump(by_alias=False)
        values["id"] = values.get("id") or _uuid32()
        values["sort"] = await self.repo.next_template_sort()
        try:
            await self.repo.insert_template(values)
            await self.session.commit()
            return values
        except Exception as exc:
            await self._rollback_and_raise(exc)

    async def update_template(self, template: AgentTemplate) -> bool:
        if template.id is None:
            return False
        try:
            affected = await self.repo.update_template(template.id, template.model_dump(by_alias=False))
            await self.session.commit()
            return affected == 1
        except Exception as exc:
            await self._rollback_and_raise(exc)

    async def delete_template(self, template_id: str) -> bool:
        row = await self.repo.get_template(template_id)
        if row is None:
            return False
        try:
            affected = await self.repo.delete_template(template_id)
            if affected == 1 and row.get("sort") is not None:
                await self.repo.reorder_templates(int(row["sort"]))
            await self.session.commit()
            return affected == 1
        except Exception as exc:
            await self._rollback_and_raise(exc)

    async def batch_delete_templates(self, ids: Sequence[str]) -> bool:
        try:
            affected = await self.repo.delete_templates(ids)
            await self.session.commit()
            return affected > 0
        except Exception as exc:
            await self._rollback_and_raise(exc)

    async def report_chat(self, report: AgentChatHistoryReport) -> bool:
        agent = await self.repo.get_agent_by_device_mac(report.mac_address)
        if agent is None or agent.get("id") is None:
            return False
        now = shanghai_now_naive()
        report_at = now
        if report.report_time is not None:
            report_at = datetime.fromtimestamp(
                report.report_time / 1000,
                ZoneInfo(get_settings().timezone),
            ).replace(tzinfo=None)
        try:
            audio_id: str | None = None
            history_conf = agent.get("chat_history_conf")
            if history_conf is not None and int(history_conf) == 2:
                if report.audio_base64:
                    try:
                        audio = base64.b64decode(report.audio_base64, validate=True)
                        audio_id = _uuid32()
                        await self.repo.insert_chat_audio(audio_id, audio)
                    except (ValueError, TypeError):
                        audio_id = None
            if history_conf is not None and int(history_conf) in {1, 2}:
                await self.repo.insert_chat_history(
                    {
                        "mac_address": report.mac_address,
                        "agent_id": agent["id"],
                        "session_id": report.session_id,
                        "chat_type": report.chat_type,
                        "content": report.content,
                        "audio_id": audio_id,
                        "created_at": report_at,
                    }
                )
            await java_set(f"agent:device:lastConnected:{agent['id']}", now, 86400)
            device = await self.repo.get_device_by_mac(report.mac_address)
            if device is not None:
                await self.repo.update_device_connection(str(device["id"]), now)
            await self.session.commit()
            return True
        except Exception as exc:
            await self._rollback_and_raise(exc)

    async def session_agent(self, session_id: str) -> str:
        agent_id = await self.repo.get_session_agent_id(session_id)
        if not agent_id:
            raise AppError(ERROR_AGENT_NOT_FOUND)
        await self.require_agent(agent_id, permission=False)
        return agent_id

    async def sessions(
        self,
        agent_id: str,
        page: int | str | None,
        limit: int | str | None,
    ) -> dict[str, Any]:
        # Java checks ownership before reading the raw request-param map.  This
        # makes a missing agent return 10169 even when page/limit are absent.
        await self.require_agent_permission(agent_id)
        if page is None or limit is None:
            raise AppError(500)
        try:
            page_number = int(page)
            limit_number = int(limit)
        except ValueError as exc:
            # AgentChatHistoryServiceImpl dereferences and parses both values;
            # absent or malformed values reach the generic exception handler.
            raise AppError(500) from exc
        rows, total = await self.repo.list_sessions(agent_id, page_number, limit_number)
        return {"list": rows, "total": total}

    async def history(self, agent_id: str, session_id: str) -> list[dict[str, Any]]:
        return await self.repo.get_chat_history(agent_id, session_id)

    async def recent_user_history(self, agent_id: str) -> list[dict[str, Any]]:
        rows = await self.repo.get_recent_user_history(agent_id)
        for row in rows:
            content = row.get("content")
            parsed = _json_load(content, None)
            if isinstance(parsed, dict) and "content" in parsed and parsed["content"] is not None:
                row["content"] = str(parsed["content"])
        return rows

    async def require_audio_permission(self, audio_id: str) -> None:
        agent_id = await self.repo.get_audio_agent_id(audio_id)
        if not agent_id or not await self.has_agent_permission(agent_id):
            raise AppError(ERROR_NO_PERMISSION)

    async def audio_content(self, audio_id: str) -> str | None:
        await self.require_audio_permission(audio_id)
        return await self.repo.get_audio_content(audio_id)

    async def issue_audio_token(self, audio_id: str) -> str | None:
        await self.require_audio_permission(audio_id)
        if await self.repo.get_chat_audio(audio_id) is None:
            return None
        token = str(uuid.uuid4())
        await java_set(f"agent:audio:id:{token}", audio_id, 300)
        return token

    async def consume_audio_token(self, token: str) -> bytes | None:
        key = f"agent:audio:id:{token}"
        audio_id = await java_get(key)
        if not isinstance(audio_id, str) or not audio_id.strip():
            return None
        audio = await self.repo.get_chat_audio(audio_id)
        if audio is None:
            return None
        from app.core.redis import get_redis

        await get_redis().delete(key)
        return audio

    async def issue_history_token(self, agent_id: str, session_id: str) -> str:
        await self.require_agent(agent_id)
        token = str(uuid.uuid4())
        await java_set(f"agent:chat:history:{token}", f"{agent_id}:{session_id}", 86400)
        return token

    async def consume_history_download(self, token: str, *, previous: bool) -> str:
        from app.core.redis import get_redis

        key = f"agent:chat:history:{token}"
        value = await java_get(key)
        if not isinstance(value, str) or not value.strip():
            raise AppError(10136)
        try:
            parts = value.split(":")
            if len(parts) != 2:
                raise AppError(10137)
            agent_id, session_id = parts
            session_ids = [session_id]
            if previous:
                sessions, _ = await self.repo.list_sessions(agent_id, 1, 1000)
                index = next(
                    (position for position, item in enumerate(sessions) if item.get("session_id") == session_id), -1
                )
                if index >= 0:
                    session_ids = [str(item["session_id"]) for item in sessions[index : index + 21]]
            chunks: list[str] = []
            for selected_session in session_ids:
                messages = await self.repo.get_chat_history(agent_id, selected_session)
                lines: list[str] = []
                if messages:
                    created = messages[0].get("created_at")
                    if isinstance(created, datetime):
                        lines.append(created.strftime("%Y-%m-%d %H:%M:%S"))
                    elif created is not None:
                        lines.append(str(created))
                for message in messages:
                    user_message = int(message.get("chat_type") or 0) == 1
                    role = message_for(10138 if user_message else 10139, self.language)
                    direction = ">>" if user_message else "<<"
                    created = message.get("created_at")
                    stamp = created.strftime("%Y-%m-%d %H:%M:%S") if isinstance(created, datetime) else str(created)
                    lines.append(f"[{role}]-[{stamp}]{direction}:{message.get('content')}")
                chunks.append("\n".join(lines))
            return "\n\n".join(chunks) + ("\n" if chunks and chunks[-1] else "")
        finally:
            await get_redis().delete(key)

    async def mcp_address(self, agent_id: str) -> str | None:
        endpoint = await SystemParamService(self.session).get_value("server.mcp_endpoint", from_cache=True)
        return build_agent_mcp_address(endpoint, agent_id)

    async def mcp_tools(self, agent_id: str) -> list[str]:
        address = await self.mcp_address(agent_id)
        return [] if not address else await list_mcp_tools(address)

    async def generate_chat_summary(self, session_id: str) -> bool:
        try:
            first = await self.repo.fetch_one(
                "SELECT agent_id,mac_address FROM ai_agent_chat_history WHERE session_id=:id LIMIT 1",
                {"id": session_id},
            )
            if first is None or not first.get("mac_address"):
                return False
            device = await self.repo.get_device_by_mac(str(first["mac_address"]))
            if device is None or not device.get("agent_id"):
                return False
            agent = await self.repo.get_agent(str(device["agent_id"]))
            if agent is None:
                return False
            memory_model = agent.get("mem_model_id")
            if memory_model is None or memory_model == MEMORY_REPORT_ONLY:
                return True
            if memory_model in {MEMORY_NO_MEM, MEMORY_MEM0AI, MEMORY_POWERMEM}:
                return True
            messages = await self.repo.get_chat_history(str(agent["id"]), session_id)
            meaningful = self._meaningful_messages(messages)
            if not meaningful:
                return False
            conversation = "".join(f"消息{index}: {message}\n" for index, message in enumerate(meaningful, 1))
            model = await self._summary_model(agent)
            config = _json_load(model.get("config_json") if model else None, {})
            if not config:
                return False
            prompt = SUMMARY_PROMPT.replace(
                "{history_memory}", str(agent.get("summary_memory") or "无历史记忆")
            ).replace("{conversation}", conversation)
            summary = await openai_completion(
                config,
                prompt,
                temperature=0.2,
                max_tokens=2000,
                timeout=get_settings().external_request_timeout_seconds,
            )
            if not summary or summary in {"服务暂不可用", "总结生成失败"}:
                return False
            if len(summary) > 1800:
                summary = summary[:1800] + "..."
            await self.update_agent(
                str(agent["id"]),
                AgentUpdate(summary_memory=summary),
                check_permission=False,
                create_snapshot=False,
            )
            return True
        except Exception:
            logger.exception("Failed to generate chat summary for session %s", session_id)
            await self.session.rollback()
            return False

    async def generate_chat_title(self, session_id: str) -> bool:
        try:
            agent_id = await self.repo.get_session_agent_id(session_id)
            if not agent_id:
                return False
            agent = await self.repo.get_agent(agent_id)
            if agent is None:
                return False
            meaningful = self._meaningful_messages(await self.repo.get_chat_history(agent_id, session_id))
            if not meaningful:
                return False
            conversation = "".join(f"消息{index}: {message}\n" for index, message in enumerate(meaningful, 1))
            model = await self._summary_model(agent)
            config = _json_load(model.get("config_json") if model else None, {})
            if not config:
                return False
            title = await openai_completion(
                config,
                TITLE_PROMPT.replace("{conversation}", conversation),
                temperature=0.3,
                max_tokens=50,
                timeout=get_settings().external_request_timeout_seconds,
            )
            if not title or not title.strip():
                return False
            title = _TITLE_PUNCTUATION.sub("", title.strip())[:15]
            await self.repo.upsert_chat_title(session_id, title, shanghai_now_naive(), _uuid32())
            await self.session.commit()
            return True
        except Exception:
            logger.exception("Failed to generate chat title for session %s", session_id)
            await self.session.rollback()
            return False

    async def _summary_model(self, agent: Mapping[str, Any]) -> dict[str, Any] | None:
        # OpenAIStyleLLMServiceImpl.isAvailable() first requires a usable default
        # model even when a concrete SLM model id is supplied.
        default = await self.repo.get_default_llm_config()
        default_config = _json_load(default.get("config_json") if default else None, {})
        if not default_config.get("base_url") or not default_config.get("api_key"):
            return None
        if agent.get("slm_model_id"):
            return await self.repo.get_model_config(str(agent["slm_model_id"]))
        return default

    def _meaningful_messages(self, messages: Sequence[Mapping[str, Any]]) -> list[str]:
        result: list[str] = []
        for message in messages:
            if int(message.get("chat_type") or 0) != 1:
                continue
            content = str(message.get("content") or "")
            match = re.search(r"\{.*?\}", content, re.DOTALL)
            if match:
                parsed = _json_load(match.group(0), None)
                if isinstance(parsed, dict) and parsed.get("content") is not None:
                    content = str(parsed["content"])
                else:
                    field = re.search(r'"content"\s*:\s*"([^"]*)"', match.group(0))
                    content = field.group(1) if field else match.group(0)
            if (
                len(content) >= 5
                and not _DEVICE_CONTROL.search(content)
                and not _WEATHER.search(content)
                and not _DATE_WORDS.search(content)
            ):
                result.append(content)
        return result

    async def _snapshot_data(self, agent_id: str) -> dict[str, Any]:
        detail = await self.repo.get_agent(agent_id)
        if detail is None:
            raise AppError(ERROR_AGENT_NOT_FOUND)
        functions = [
            {
                "pluginId": row.get("plugin_id"),
                "paramInfo": _json_load(row.get("param_info"), {}),
            }
            for row in await self.repo.get_agent_plugins(agent_id)
        ]
        tags = await self.repo.get_agent_tags(agent_id)
        snapshot_tags = [{"id": row["id"], "tagName": row["tag_name"], "sort": index} for index, row in enumerate(tags)]
        scalar_mapping = {
            "agentCode": "agent_code",
            "agentName": "agent_name",
            "asrModelId": "asr_model_id",
            "vadModelId": "vad_model_id",
            "llmModelId": "llm_model_id",
            "slmModelId": "slm_model_id",
            "vllmModelId": "vllm_model_id",
            "ttsModelId": "tts_model_id",
            "ttsVoiceId": "tts_voice_id",
            "ttsLanguage": "tts_language",
            "ttsVolume": "tts_volume",
            "ttsRate": "tts_rate",
            "ttsPitch": "tts_pitch",
            "memModelId": "mem_model_id",
            "intentModelId": "intent_model_id",
            "chatHistoryConf": "chat_history_conf",
            "systemPrompt": "system_prompt",
            "summaryMemory": "summary_memory",
            "langCode": "lang_code",
            "language": "language",
            "sort": "sort",
        }
        data = {api_name: detail.get(column) for api_name, column in scalar_mapping.items()}
        context = await self.repo.get_context_provider(agent_id)
        data.update(
            functions=functions,
            contextProviders=_json_load(context.get("context_providers") if context else None, []),
            correctWordFileIds=await self.repo.get_correct_word_ids(agent_id),
            tagNames=[str(row["tag_name"]) for row in tags],
            tags=snapshot_tags,
        )
        return AgentSnapshotData.model_validate(data).model_dump(by_alias=True)

    async def _create_snapshot(self, agent_id: str, source: str) -> None:
        agent = await self.repo.get_agent(agent_id, for_update=True)
        if agent is None:
            raise AppError(ERROR_AGENT_NOT_FOUND)
        data = await self._snapshot_data(agent_id)
        previous = await self.repo.latest_snapshot(agent_id)
        if previous is None:
            changed = ["initial"]
        else:
            previous_data = _parse_snapshot_data(previous.get("snapshot_data"))
            changed = _changed_snapshot_fields(previous_data, data)
        if not changed:
            return
        await self._insert_snapshot(agent_id, int(agent.get("user_id") or 0), source, data, changed)

    async def _insert_snapshot(
        self,
        agent_id: str,
        user_id: int,
        source: str,
        data: Mapping[str, Any],
        changed_fields: Sequence[str],
        *,
        restore_from_id: str | None = None,
        restore_from_version: int | None = None,
        prune: bool = True,
    ) -> None:
        values = {
            "id": _uuid32(),
            "agent_id": agent_id,
            "user_id": user_id,
            "snapshot_data": _json_dump(_redact_snapshot_data(dict(data))),
            "changed_fields": _json_dump(list(changed_fields)),
            "source": source.strip() or "config",
            "restore_from_snapshot_id": restore_from_id,
            "restore_from_version_no": restore_from_version,
            "creator": self.actor_id,
            "created_at": shanghai_now_naive(),
            "redaction_version": CURRENT_REDACTION_VERSION,
        }
        if await self.repo.insert_snapshot_next_version(values) != 1:
            raise AppError(500, "快照版本号生成失败")
        if prune:
            await self.repo.prune_snapshots(agent_id, MAX_SNAPSHOTS_PER_AGENT)

    async def snapshot_page(self, agent_id: str, params: AgentSnapshotPage) -> dict[str, Any]:
        await self.require_snapshot_permission(agent_id)
        await self.require_agent(agent_id)
        rows, total = await self.repo.list_snapshots(
            agent_id, params.page_or_default(), params.limit_or_default(), params.max_version_no
        )
        return {"list": [self._snapshot_vo(row, include_data=False) for row in rows], "total": total}

    async def snapshot_detail(self, agent_id: str, snapshot_id: str) -> dict[str, Any]:
        await self.require_snapshot_permission(agent_id)
        await self.require_agent(agent_id, for_update=True)
        snapshot = await self._snapshot_entity(agent_id, snapshot_id)
        result = self._snapshot_vo(snapshot, include_data=True)
        next_snapshot = await self.repo.next_snapshot(agent_id, int(snapshot["version_no"]))
        result["afterSnapshotData"] = (
            _redact_snapshot_data(_parse_snapshot_data(next_snapshot.get("snapshot_data")))
            if next_snapshot is not None
            else None
        )
        current = await self._snapshot_data(agent_id)
        result["currentSnapshotData"] = _redact_snapshot_data(current)
        result["currentStateToken"] = _snapshot_state_token(current)
        return result

    async def restore_snapshot(self, agent_id: str, snapshot_id: str, state_token: str) -> None:
        try:
            await self.require_snapshot_permission(agent_id)
            agent = await self.require_agent(agent_id, for_update=True)
            snapshot = await self._snapshot_entity(agent_id, snapshot_id)
            target = _parse_snapshot_data(snapshot.get("snapshot_data"))
            if not target:
                raise AppError(500, "快照数据为空，无法恢复")
            current = await self._snapshot_data(agent_id)
            if _snapshot_state_token(current) != state_token:
                raise AppError(500, "当前配置已变化，请重新打开恢复预览后再试")
            restored = _preserve_snapshot_sensitive(target, current)
            try:
                _preserve_snapshot_sensitive(current, restored)
            except AppError as exc:
                raise AppError(500, "目标版本会移除无法写入历史的敏感配置，请先手动处理相关密钥后再恢复") from exc
            requested = _changed_snapshot_fields(current, restored)
            if not requested:
                return
            latest = await self.repo.latest_snapshot(agent_id)
            latest_data = _parse_snapshot_data(latest.get("snapshot_data")) if latest else None
            backup_changed = _changed_snapshot_fields(latest_data, current)
            backup_created = bool(backup_changed)
            if backup_created:
                await self._insert_snapshot(
                    agent_id,
                    int(agent.get("user_id") or 0),
                    "current",
                    current,
                    backup_changed,
                    prune=False,
                )
            scalar_map = {
                "agentCode": "agent_code",
                "agentName": "agent_name",
                "asrModelId": "asr_model_id",
                "vadModelId": "vad_model_id",
                "llmModelId": "llm_model_id",
                "slmModelId": "slm_model_id",
                "vllmModelId": "vllm_model_id",
                "ttsModelId": "tts_model_id",
                "ttsVoiceId": "tts_voice_id",
                "ttsLanguage": "tts_language",
                "ttsVolume": "tts_volume",
                "ttsRate": "tts_rate",
                "ttsPitch": "tts_pitch",
                "memModelId": "mem_model_id",
                "intentModelId": "intent_model_id",
                "chatHistoryConf": "chat_history_conf",
                "systemPrompt": "system_prompt",
                "summaryMemory": "summary_memory",
                "langCode": "lang_code",
                "language": "language",
                "sort": "sort",
            }
            update = {column: restored.get(api_name) for api_name, column in scalar_map.items()}
            await self._validate_llm_intent(update.get("llm_model_id"), update.get("intent_model_id"))
            if update.get("mem_model_id") == MEMORY_NO_MEM:
                await self.repo.delete_chat_history(agent_id, delete_audio=True, delete_text=True)
                update["summary_memory"] = ""
            elif update.get("mem_model_id") == MEMORY_REPORT_ONLY:
                update["summary_memory"] = ""
            update.update(updater=self.actor_id, updated_at=shanghai_now_naive())
            affected = await self.repo.update_agent(agent_id, update, include_null=True)
            if affected < 0 or affected > 1:
                raise AppError(500, "智能体快照恢复失败")
            await self.repo.delete_plugins(agent_id)
            await self.repo.replace_plugins(
                agent_id,
                [
                    {
                        "id": snowflake.next_id(),
                        "plugin_id": str(item.get("pluginId") or ""),
                        "param_info": _json_dump(item.get("paramInfo") or {}),
                    }
                    for item in restored.get("functions") or []
                    if isinstance(item, dict)
                ],
            )
            now = shanghai_now_naive()
            await self.repo.upsert_context_provider(
                agent_id,
                _json_dump(restored.get("contextProviders") or []),
                _uuid32(),
            )
            correct_ids = [str(value) for value in restored.get("correctWordFileIds") or []]
            await self.repo.replace_correct_words(
                agent_id, correct_ids, self.actor_id, now, [_uuid32() for _ in correct_ids]
            )
            await self._restore_snapshot_tags(agent_id, restored, now)
            actual = await self._snapshot_data(agent_id)
            actual_changed = _changed_snapshot_fields(current, actual)
            if actual_changed:
                await self._insert_snapshot(
                    agent_id,
                    int(agent.get("user_id") or 0),
                    "restore",
                    actual,
                    actual_changed,
                    restore_from_id=str(snapshot["id"]),
                    restore_from_version=int(snapshot["version_no"]),
                    prune=False,
                )
            if backup_created or actual_changed:
                await self.repo.prune_snapshots(agent_id, MAX_SNAPSHOTS_PER_AGENT)
            await self.session.commit()
        except Exception as exc:
            await self._rollback_and_raise(exc)

    async def _restore_snapshot_tags(self, agent_id: str, data: Mapping[str, Any], now: datetime) -> None:
        snapshot_tags = data.get("tags")
        if not isinstance(snapshot_tags, list) or not snapshot_tags:
            await self._replace_agent_tags(agent_id, None, [str(value) for value in data.get("tagNames") or []])
            return
        relations: list[dict[str, Any]] = []
        for index, item in enumerate(snapshot_tags):
            if not isinstance(item, dict) or not str(item.get("tagName") or "").strip():
                continue
            tag = await self.repo.get_tag(str(item.get("id") or "")) if item.get("id") else None
            if tag is None:
                tag = await self.repo.find_any_tag_by_name(str(item["tagName"]))
            if tag is not None and int(tag.get("deleted") or 0) == 1:
                raise AppError(500, "快照引用的标签已被删除，无法恢复，请先重新创建或选择标签")
            if tag is None:
                tag = {
                    "id": _uuid32(),
                    "tag_name": str(item["tagName"]),
                    "sort": int(item.get("sort") or 0),
                    "deleted": 0,
                    "creator": self.actor_id,
                    "created_at": now,
                    "updater": self.actor_id,
                    "updated_at": now,
                }
                await self.repo.insert_tag(tag)
            relations.append(
                {
                    "id": _uuid32(),
                    "agent_id": agent_id,
                    "tag_id": tag["id"],
                    "sort": index,
                    "creator": self.actor_id,
                    "created_at": now,
                    "updater": self.actor_id,
                    "updated_at": now,
                }
            )
        await self.repo.replace_tag_relations(agent_id, relations)

    async def delete_snapshot(self, agent_id: str, snapshot_id: str) -> None:
        try:
            await self.require_snapshot_permission(agent_id)
            await self.require_agent(agent_id, for_update=True)
            snapshot = await self._snapshot_entity(agent_id, snapshot_id)
            if int(snapshot["version_no"]) == await self.repo.snapshot_max_version(agent_id):
                raise AppError(500, "最新历史版本不能删除")
            await self.repo.delete_snapshot(snapshot_id)
            await self.session.commit()
        except Exception as exc:
            await self._rollback_and_raise(exc)

    async def _snapshot_entity(self, agent_id: str, snapshot_id: str) -> dict[str, Any]:
        snapshot = await self.repo.get_snapshot(snapshot_id)
        if snapshot is None or str(snapshot.get("agent_id")) != agent_id:
            raise AppError(500, "快照不存在")
        return snapshot

    def _snapshot_vo(self, row: Mapping[str, Any], *, include_data: bool) -> dict[str, Any]:
        result = {
            "id": row.get("id"),
            "agentId": row.get("agent_id"),
            "userId": row.get("user_id"),
            "versionNo": row.get("version_no"),
            "changedFields": _json_load(row.get("changed_fields"), []),
            "fieldOrder": list(SNAPSHOT_FIELD_ORDER),
            "source": row.get("source"),
            "restoreFromSnapshotId": row.get("restore_from_snapshot_id"),
            "restoreFromVersionNo": row.get("restore_from_version_no"),
            "creator": row.get("creator"),
            "createdAt": row.get("created_at"),
            "snapshotData": None,
            "afterSnapshotData": None,
            "currentSnapshotData": None,
            "currentStateToken": None,
        }
        if include_data:
            result["snapshotData"] = _redact_snapshot_data(_parse_snapshot_data(row.get("snapshot_data")))
        return result

    async def redact_legacy_snapshots(self) -> int:
        after_id: str | None = None
        migrated = 0
        while True:
            batch = await self.repo.list_legacy_snapshots(
                after_id, LEGACY_REDACTION_BATCH_SIZE, CURRENT_REDACTION_VERSION
            )
            if not batch:
                return migrated
            try:
                for snapshot in batch:
                    raw = _json_load(snapshot.get("snapshot_data"), None)
                    if not isinstance(raw, dict):
                        raise AppError(500, f"历史快照数据无法解析，已中止脱敏迁移: {snapshot['id']}")
                    migrated += await self.repo.update_redacted_snapshot(
                        str(snapshot["id"]),
                        _json_dump(_redact_sensitive_map(raw)),
                        CURRENT_REDACTION_VERSION,
                    )
                await self.session.commit()
            except Exception as exc:
                await self._rollback_and_raise(exc)
            after_id = str(batch[-1]["id"])

    async def voiceprint_list(self, agent_id: str) -> list[dict[str, Any]]:
        configured = await SystemParamService(self.session).get_value("server.voice_print", from_cache=True)
        if configured is None or not configured.strip() or configured == "null":
            raise AppError(ERROR_VOICEPRINT_NOT_CONFIGURED)
        return await self.repo.list_voiceprints(agent_id, self.actor_id)

    async def _voiceprint_audio(self, agent_id: str | None, audio_id: str | None) -> bytes:
        if not agent_id or not audio_id or not await self.repo.is_audio_owned(audio_id, agent_id):
            raise AppError(10085)
        audio = await self.repo.get_chat_audio(audio_id)
        if not audio:
            raise AppError(10086)
        return audio

    async def _voiceprint_client(self) -> VoicePrintClient:
        configured = await SystemParamService(self.session).get_value("server.voice_print", from_cache=True)
        try:
            return VoicePrintClient(configured or "", timeout=get_settings().external_request_timeout_seconds)
        except VoicePrintIntegrationError as exc:
            raise AppError(exc.code, exc.message, exc.params) from exc

    async def create_voiceprint(self, dto: AgentVoicePrintSave) -> bool:
        audio = await self._voiceprint_audio(dto.agent_id, dto.audio_id)
        client = await self._voiceprint_client()
        ids = await self.repo.list_voiceprint_ids(str(dto.agent_id))
        try:
            identified = await client.identify(ids, audio)
            if identified and identified[1] is not None and identified[1] > 0.5:
                existing = await self.repo.get_voiceprint(str(identified[0])) if identified[0] else None
                name = str(existing.get("source_name") if existing else "未知用户")
                raise AppError(10080, params=(name,))
            now = shanghai_now_naive()
            voiceprint_id = _uuid32()
            await self.repo.insert_voiceprint(
                {
                    "id": voiceprint_id,
                    "agent_id": dto.agent_id,
                    "audio_id": dto.audio_id,
                    "source_name": dto.source_name,
                    "introduce": dto.introduce,
                    "creator": self.actor_id,
                    "create_date": now,
                    "updater": self.actor_id,
                    "update_date": now,
                }
            )
            await client.register(voiceprint_id, audio)
            await self.session.commit()
            return True
        except VoicePrintIntegrationError as exc:
            await self.session.rollback()
            raise AppError(exc.code, exc.message, exc.params) from exc
        except Exception as exc:
            await self.session.rollback()
            if isinstance(exc, AppError):
                raise
            raise AppError(10046) from exc

    async def update_voiceprint(self, dto: AgentVoicePrintUpdate) -> bool:
        if dto.id is None:
            return False
        existing = await self.repo.get_voiceprint(dto.id, self.actor_id)
        if existing is None:
            return False
        client = await self._voiceprint_client()
        audio: bytes | None = None
        if dto.audio_id and dto.audio_id != existing.get("audio_id"):
            audio = await self._voiceprint_audio(str(existing["agent_id"]), dto.audio_id)
            try:
                identified = await client.identify(
                    await self.repo.list_voiceprint_ids(str(existing["agent_id"])), audio
                )
            except VoicePrintIntegrationError as exc:
                raise AppError(exc.code, exc.message, exc.params) from exc
            if identified and identified[1] is not None and identified[1] > 0.5 and identified[0] != dto.id:
                duplicate = await self.repo.get_voiceprint(str(identified[0])) if identified[0] else None
                name = str(duplicate.get("source_name") if duplicate else "未知用户")
                raise AppError(10082, params=(name,))
        try:
            values = {
                "audio_id": dto.audio_id,
                "source_name": dto.source_name,
                "introduce": dto.introduce,
                "updater": self.actor_id,
                "update_date": shanghai_now_naive(),
            }
            affected = await self.repo.update_voiceprint(dto.id, self.actor_id, values)
            if affected != 1:
                await self.session.rollback()
                return False
            if audio is not None:
                await client.cancel(dto.id)
                await client.register(dto.id, audio)
            await self.session.commit()
            return True
        except VoicePrintIntegrationError as exc:
            await self.session.rollback()
            raise AppError(exc.code, exc.message, exc.params) from exc
        except Exception as exc:
            await self.session.rollback()
            if isinstance(exc, AppError):
                raise
            raise AppError(10083) from exc

    async def delete_voiceprint(self, voiceprint_id: str) -> bool:
        try:
            affected = await self.repo.delete_voiceprint(voiceprint_id, self.actor_id)
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            raise AppError(10081) from exc
        if affected == 1:
            asyncio.create_task(_cancel_voiceprint_after_commit(voiceprint_id))
        return affected == 1


def _parse_snapshot_data(value: Any) -> dict[str, Any] | None:
    parsed = _json_load(value, None)
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise AppError(500, "快照数据无法解析")
    # Snapshot payloads intentionally ignore fields unknown to this application version.
    accepted = set(SNAPSHOT_FIELD_ORDER) | {"tags"}
    return AgentSnapshotData.model_validate({key: item for key, item in parsed.items() if key in accepted}).model_dump(
        by_alias=True
    )


def _normalized_key(value: str | None) -> str:
    return re.sub("[^a-z0-9]", "", (value or "").lower())


def _is_sensitive_key(value: str | None) -> bool:
    key = _normalized_key(value)
    return (
        key == "authorization"
        or "authorization" in key
        or "authentication" in key
        or key == "auth"
        or key.endswith("auth")
        or key in {"cookie", "cookie2", "setcookie", "setcookie2"}
        or key.endswith("cookie")
        or key == "session"
        or key.endswith("session")
        or any(marker in key for marker in ("sessionid", "sessionkey", "sessiontoken", "sessioncookie"))
        or key.endswith("sessid")
        or key == "token"
        or key.endswith("token")
        or any(
            marker in key
            for marker in (
                "apikey",
                "appkey",
                "accesskey",
                "subscriptionkey",
                "privatekey",
                "password",
                "passwd",
                "secret",
                "credential",
            )
        )
    )


def _is_url_key(value: str | None) -> bool:
    key = _normalized_key(value)
    return key.endswith(("url", "uri", "endpoint", "webhook"))


def _is_webhook_semantic_key(value: str | None) -> bool:
    key = _normalized_key(value)
    return "webhook" in key or key in {"hook", "hooks"} or key.endswith(("hook", "hooks"))


def _resolve_url_semantic_key(parent_key: str | None, child_key: str | None) -> str | None:
    if _is_webhook_semantic_key(child_key):
        return child_key
    if _is_webhook_semantic_key(parent_key):
        return parent_key if not child_key else f"{parent_key}.{child_key}"
    return child_key


def _looks_like_url(value: str) -> bool:
    return value.startswith("//") or bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value))


def _should_treat_as_url(key: str | None, value: Any) -> bool:
    return isinstance(value, str) and (_is_url_key(key) or _is_webhook_semantic_key(key) or _looks_like_url(value))


def _split_sensitive_url(value: str) -> tuple[str, str | None, str | None, str | None]:
    remaining = value or ""
    fragment: str | None = None
    if "#" in remaining:
        remaining, fragment = remaining.split("#", 1)
    query: str | None = None
    if "?" in remaining:
        remaining, query = remaining.split("?", 1)
    user_info: str | None = None
    match = re.match(r"^(?P<prefix>(?:[A-Za-z][A-Za-z0-9+.-]*:)?//)(?P<authority>[^/]*)(?P<path>/.*)?$", remaining)
    if match and "@" in match.group("authority"):
        authority = match.group("authority")
        user_info, authority = authority.rsplit("@", 1)
        remaining = f"{match.group('prefix')}{authority}{match.group('path') or ''}"
    return remaining, user_info, query, fragment


def _join_sensitive_url(base: str, user_info: str | None, query: str | None, fragment: str | None) -> str:
    result = base
    if user_info is not None:
        match = re.match(r"^(?P<prefix>(?:[A-Za-z][A-Za-z0-9+.-]*:)?//)(?P<rest>.*)$", result)
        if not match:
            raise AppError(500, "带用户凭据的 URL 格式无效，无法安全恢复")
        result = f"{match.group('prefix')}{user_info}@{match.group('rest')}"
    if query is not None:
        result += f"?{query}"
    if fragment is not None:
        result += f"#{fragment}"
    return result


def _url_host_and_path(base: str) -> tuple[str, str, list[str]] | None:
    match = re.match(r"^(?P<prefix>(?:[A-Za-z][A-Za-z0-9+.-]*:)?//[^/]*)(?P<path>/.*)?$", base)
    if match:
        prefix = match.group("prefix")
        host = urlsplit(prefix if "://" in prefix else f"http:{prefix}").hostname or ""
        path = match.group("path") or ""
        return prefix, host.lower(), path.split("/")
    if not base or any(character.isspace() for character in base):
        return None
    return "", "", base.split("/")


def _capability_secret(value: str) -> bool:
    normalized = _normalized_key(value)
    if any(
        marker in normalized
        for marker in ("secret", "token", "capability", "credential", "signature", "apikey", "accesskey", "authkey")
    ):
        return True
    if len(value) < 20:
        return False
    categories = sum(
        (
            any(character.isalpha() for character in value),
            any(character.isdigit() for character in value),
            any(not character.isalnum() for character in value),
        )
    )
    return len(set(value)) >= 10 and categories >= 2


def _redact_url_path(base: str, semantic_key: str | None) -> str:
    parsed = _url_host_and_path(base)
    if parsed is None:
        return base
    prefix, host, segments = parsed
    slots: list[tuple[int, int, str]] = []
    if host in {"hooks.slack.com", "hooks.slack-gov.com"}:
        for index, segment in enumerate(segments):
            if segment.lower() == "services" and index + 3 < len(segments) and all(segments[index + 1 : index + 4]):
                slots.append((index + 3, index + 4, SECRET_PLACEHOLDER))
    if (
        host == "discord.com"
        or host.endswith(".discord.com")
        or host == "discordapp.com"
        or host.endswith(".discordapp.com")
    ):
        for index, segment in enumerate(segments):
            if (
                segment.lower() == "webhooks"
                and (
                    (index >= 1 and segments[index - 1].lower() == "api")
                    or (
                        index >= 2
                        and segments[index - 2].lower() == "api"
                        and re.fullmatch(r"v\d+", segments[index - 1], re.IGNORECASE) is not None
                    )
                )
                and index + 2 < len(segments)
                and segments[index + 1]
                and segments[index + 2]
            ):
                slots.append((index + 2, index + 3, SECRET_PLACEHOLDER))
    if host == "api.telegram.org":
        for index, segment in enumerate(segments):
            if segment.lower().startswith("bot") and ":" in segment:
                prefix_part, secret = segment.split(":", 1)
                if len(prefix_part) > 3 and secret:
                    slots.append((index, index + 1, f"{prefix_part}:{SECRET_PLACEHOLDER}"))
    if not slots:
        markers = {"webhook", "webhooks", "hook", "hooks"}
        for index, segment in enumerate(segments):
            suffix = [value for value in segments[index + 1 :] if value]
            host_labels = set(host.split("."))
            if (
                segment.lower() in markers
                and suffix
                and (
                    _is_webhook_semantic_key(semantic_key)
                    or bool(markers.intersection(host_labels))
                    or any(_capability_secret(item) for item in suffix)
                )
            ):
                slots.append((index + 1, len(segments), SECRET_PLACEHOLDER))
                break
    if not slots and _is_webhook_semantic_key(semantic_key):
        last = next((index for index in range(len(segments) - 1, -1, -1) if segments[index]), -1)
        if last >= 0:
            slots.append((last, last + 1, SECRET_PLACEHOLDER))
    for start, end, replacement in sorted(slots, reverse=True):
        segments[start:end] = [replacement]
    return prefix + "/".join(segments)


def _url_parameters(value: str | None) -> list[tuple[str, str, bool]]:
    if value is None:
        return []
    result: list[tuple[str, str, bool]] = []
    for item in value.split("&"):
        if "=" in item:
            key, raw_value = item.split("=", 1)
            result.append((key, raw_value, True))
        else:
            result.append((item, "", False))
    return result


def _parameter_sensitive(raw_key: str) -> bool:
    try:
        key = unquote_plus(raw_key)
    except ValueError:
        key = raw_key
    normalized = _normalized_key(key)
    return _is_sensitive_key(key) or normalized in {
        "key",
        "sig",
        "signature",
        "xamzsignature",
        "xgoogsignature",
        "sas",
    }


def _url_parameter_identity(raw_key: str) -> str:
    try:
        decoded = unquote_plus(raw_key)
    except ValueError:
        decoded = raw_key
    return _normalized_key(decoded)


def _redact_url_parameters(value: str | None) -> str | None:
    if value is None:
        return None
    result: list[str] = []
    for key, item, has_equals in _url_parameters(value):
        if _parameter_sensitive(key):
            result.append(f"{key}={SECRET_PLACEHOLDER}" if has_equals else key)
        else:
            result.append(f"{key}={item}" if has_equals else key)
    return "&".join(result)


def _redact_sensitive_url(value: str | None, semantic_key: str | None = None) -> str | None:
    if value is None:
        return None
    base, user_info, query, fragment = _split_sensitive_url(value)
    redacted_fragment = (
        _redact_url_parameters(fragment)
        if fragment is not None and ("=" in fragment or "&" in fragment)
        else SECRET_PLACEHOLDER
        if fragment is not None
        else None
    )
    return _join_sensitive_url(
        _redact_url_path(base, semantic_key),
        SECRET_PLACEHOLDER if user_info is not None else None,
        _redact_url_parameters(query),
        redacted_fragment,
    )


def _preserve_url_parameters(target: str | None, current: str | None) -> str | None:
    if target is None:
        return None
    target_values: dict[str, list[tuple[str, str, bool]]] = defaultdict(list)
    current_values: dict[str, list[tuple[str, str, bool]]] = defaultdict(list)
    for item in _url_parameters(target):
        if _parameter_sensitive(item[0]):
            target_values[_url_parameter_identity(item[0])].append(item)
    for item in _url_parameters(current):
        if _parameter_sensitive(item[0]):
            current_values[_url_parameter_identity(item[0])].append(item)
    restored: list[str] = []
    for key, value, has_equals in _url_parameters(target):
        if _parameter_sensitive(key):
            identity = _url_parameter_identity(key)
            matches = current_values.get(identity, [])
            if len(target_values.get(identity, [])) != 1 or len(matches) != 1 or SECRET_PLACEHOLDER in matches[0][1]:
                raise AppError(500, "快照 URL 敏感参数无法与当前配置可靠匹配")
            current_key, current_value, current_equals = matches[0]
            del current_key
            restored.append(f"{key}={current_value}" if current_equals else key)
        else:
            restored.append(f"{key}={value}" if has_equals else key)
    return "&".join(restored)


def _preserve_sensitive_url(target: str | None, current: str | None, semantic_key: str | None = None) -> str | None:
    if target is None:
        return None
    if SECRET_PLACEHOLDER not in target:
        return target
    if current is None or SECRET_PLACEHOLDER in current:
        raise AppError(500, "快照 URL 敏感信息无法与当前配置可靠匹配")
    if _redact_sensitive_url(current, semantic_key) == target:
        return current
    target_base, target_user, target_query, target_fragment = _split_sensitive_url(target)
    current_base, current_user, current_query, current_fragment = _split_sensitive_url(current)
    copies_sensitive = (
        target_user is not None
        or SECRET_PLACEHOLDER in target_base
        or any(_parameter_sensitive(item[0]) for item in _url_parameters(target_query))
        or target_fragment is not None
    )
    if copies_sensitive and _redact_url_path(target_base, semantic_key) != _redact_url_path(current_base, semantic_key):
        raise AppError(500, "快照 URL 敏感信息无法与当前配置的公开地址标识匹配")
    if SECRET_PLACEHOLDER in target_base:
        if _redact_url_path(current_base, semantic_key) != target_base:
            raise AppError(500, "快照 URL 路径敏感信息无法与当前配置的公开标识唯一匹配")
        target_base = current_base
    if target_user == SECRET_PLACEHOLDER:
        if not current_user or SECRET_PLACEHOLDER in current_user:
            raise AppError(500, "快照 URL 用户凭据无法与当前配置匹配")
        target_user = current_user
    target_query = _preserve_url_parameters(target_query, current_query)
    if target_fragment == SECRET_PLACEHOLDER:
        if current_fragment is None or SECRET_PLACEHOLDER in current_fragment:
            raise AppError(500, "快照 URL 片段敏感信息无法与当前配置匹配")
        target_fragment = current_fragment
    elif target_fragment is not None:
        target_fragment = _preserve_url_parameters(target_fragment, current_fragment)
    return _join_sensitive_url(target_base, target_user, target_query, target_fragment)


def _map_value(mapping: Mapping[Any, Any] | None, key: str) -> Any:
    if mapping is None:
        return None
    if key in mapping:
        return mapping[key]
    for item_key, value in mapping.items():
        if str(item_key).lower() == key.lower():
            return value
    return None


def _structured_sensitive_key(mapping: Mapping[Any, Any] | None) -> str | None:
    for discriminator in ("key", "name"):
        value = _map_value(mapping, discriminator)
        if value is not None and _is_sensitive_key(str(value)):
            return str(value)
    return None


def _redact_sensitive_value(value: Any, parent_key: str | None = None) -> Any:
    if _should_treat_as_url(parent_key, value):
        return _redact_sensitive_url(str(value), parent_key)
    if isinstance(value, dict):
        return _redact_sensitive_map(value, parent_key)
    if isinstance(value, list):
        return [_redact_sensitive_value(item, parent_key) for item in value]
    return copy.deepcopy(value)


def _redact_sensitive_map(mapping: Mapping[Any, Any] | None, parent_key: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if mapping is None:
        return result
    structured = _structured_sensitive_key(mapping)
    for raw_key, value in mapping.items():
        if raw_key is None:
            continue
        key = str(raw_key)
        semantic_key = _resolve_url_semantic_key(parent_key, key)
        if _is_sensitive_key(key) or (structured is not None and key.lower() == "value"):
            result[key] = SECRET_PLACEHOLDER
        elif _should_treat_as_url(semantic_key, value):
            result[key] = _redact_sensitive_url(str(value), semantic_key)
        else:
            result[key] = _redact_sensitive_value(value, semantic_key)
    return result


def _contains_sensitive(value: Any, parent_key: str | None = None) -> bool:
    if value == SECRET_PLACEHOLDER:
        return True
    if isinstance(value, dict):
        if _structured_sensitive_key(value) is not None:
            return True
        return any(
            _is_sensitive_key(str(key))
            or (
                _should_treat_as_url(_resolve_url_semantic_key(parent_key, str(key)), item)
                and SECRET_PLACEHOLDER
                in str(_redact_sensitive_url(str(item), _resolve_url_semantic_key(parent_key, str(key))))
            )
            or _contains_sensitive(item, _resolve_url_semantic_key(parent_key, str(key)))
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive(item, parent_key) for item in value)
    return bool(
        _should_treat_as_url(parent_key, value)
        and SECRET_PLACEHOLDER in str(_redact_sensitive_url(str(value), parent_key))
    )


def _stable_identities(value: Any, parent_key: str | None = None) -> list[str]:
    if _should_treat_as_url(parent_key, value):
        return [f"url:{_url_public_identity(str(value), parent_key)}"]
    if not isinstance(value, dict):
        return []
    identities: list[str] = []
    for field in ("id", "name", "key", "url"):
        item = _map_value(value, field)
        if item is None or not str(item).strip():
            continue
        normalized = _url_public_identity(str(item), field) if field == "url" else str(item).strip()
        if field in {"name", "key"}:
            normalized = normalized.lower()
        identities.append(f"{field}:{normalized}")
    if value:
        identities.append(f"fingerprint:{_json_dump(_normalize_map(value, parent_key), sort_keys=True)}")
    return identities


def _preserve_sensitive_value(target: Any, current: Any, parent_key: str | None = None) -> Any:
    if _should_treat_as_url(parent_key, target):
        return _preserve_sensitive_url(str(target), str(current) if isinstance(current, str) else None, parent_key)
    if isinstance(target, dict):
        return _preserve_sensitive_map(target, current if isinstance(current, dict) else None, parent_key)
    if isinstance(target, list):
        current_list = current if isinstance(current, list) else []
        target_index: dict[str, list[Any]] = defaultdict(list)
        current_index: dict[str, list[Any]] = defaultdict(list)
        for item in target:
            for identity in _stable_identities(item, parent_key):
                target_index[identity].append(item)
        for item in current_list:
            for identity in _stable_identities(item, parent_key):
                current_index[identity].append(item)
        result: list[Any] = []
        for item in target:
            candidates = {
                id(current_index[identity][0]): current_index[identity][0]
                for identity in _stable_identities(item, parent_key)
                if len(target_index[identity]) == 1 and len(current_index.get(identity, [])) == 1
            }
            current_item = next(iter(candidates.values())) if len(candidates) == 1 else None
            if current_item is None and _contains_sensitive(item, parent_key):
                raise AppError(500, "快照中的敏感列表项缺少唯一稳定标识，无法安全恢复")
            result.append(_preserve_sensitive_value(item, current_item, parent_key))
        return result
    return copy.deepcopy(target)


def _preserve_sensitive_map(
    target: Mapping[Any, Any] | None,
    current: Mapping[Any, Any] | None,
    parent_key: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if target is None:
        return result
    structured = _structured_sensitive_key(target)
    if structured is not None:
        target_id = _normalized_key(structured)
        current_structured = _structured_sensitive_key(current)
        if current_structured is None or _normalized_key(current_structured) != target_id:
            raise AppError(500, "快照结构化敏感值的类型标识无法与当前配置唯一匹配")
    for raw_key, value in target.items():
        if raw_key is None:
            continue
        key = str(raw_key)
        semantic_key = _resolve_url_semantic_key(parent_key, key)
        current_value = _map_value(current, key)
        if _is_sensitive_key(key) or (structured is not None and key.lower() == "value"):
            if current_value is None or current_value == SECRET_PLACEHOLDER:
                raise AppError(500, "快照敏感值无法与当前配置可靠匹配")
            result[key] = copy.deepcopy(current_value)
        elif _should_treat_as_url(semantic_key, value):
            result[key] = _preserve_sensitive_url(
                str(value), str(current_value) if isinstance(current_value, str) else None, semantic_key
            )
        else:
            result[key] = _preserve_sensitive_value(value, current_value, semantic_key)
    return result


def _url_public_identity(value: str | None, semantic_key: str | None = None) -> str:
    if not value:
        return ""
    base, _user, _query, _fragment = _split_sensitive_url(value)
    return _redact_url_path(base, semantic_key)


def _redact_snapshot_data(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    result = copy.deepcopy(data)
    functions = result.get("functions")
    if isinstance(functions, list):
        for function in functions:
            if isinstance(function, dict):
                function["paramInfo"] = _redact_sensitive_map(function.get("paramInfo") or {})
    providers = result.get("contextProviders")
    if isinstance(providers, list):
        for provider in providers:
            if isinstance(provider, dict):
                provider["url"] = _redact_sensitive_url(provider.get("url"), "url")
                provider["headers"] = _redact_sensitive_map(provider.get("headers") or {})
    return result


def _preserve_snapshot_sensitive(target: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(target)
    current_functions: dict[str, dict[str, Any]] = {}
    for item in current.get("functions") or []:
        if isinstance(item, dict) and item.get("pluginId"):
            current_functions.setdefault(str(item["pluginId"]), item)
    for function in result.get("functions") or []:
        if not isinstance(function, dict):
            continue
        current_function = current_functions.get(str(function.get("pluginId")))
        function["paramInfo"] = _preserve_sensitive_map(
            function.get("paramInfo") or {},
            current_function.get("paramInfo") if current_function else None,
        )
    current_providers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    target_providers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for provider in current.get("contextProviders") or []:
        if isinstance(provider, dict):
            current_providers[_url_public_identity(provider.get("url"), "url")].append(provider)
    for provider in result.get("contextProviders") or []:
        if isinstance(provider, dict):
            target_providers[_url_public_identity(provider.get("url"), "url")].append(provider)
    for provider in result.get("contextProviders") or []:
        if not isinstance(provider, dict):
            continue
        identity = _url_public_identity(provider.get("url"), "url")
        matches = current_providers.get(identity, [])
        current_provider = (
            matches[0] if identity and len(matches) == 1 and len(target_providers[identity]) == 1 else None
        )
        if current_provider is None and (
            SECRET_PLACEHOLDER in str(_redact_sensitive_url(provider.get("url"), "url"))
            or _contains_sensitive(provider.get("headers") or {})
        ):
            raise AppError(500, "上下文源敏感配置缺少唯一 URL 标识，无法安全恢复")
        provider["url"] = _preserve_sensitive_url(
            provider.get("url"), current_provider.get("url") if current_provider else None, "url"
        )
        provider["headers"] = _preserve_sensitive_map(
            provider.get("headers") or {}, current_provider.get("headers") if current_provider else None
        )
    return result


def _normalize_value(value: Any, parent_key: str | None = None) -> Any:
    if _should_treat_as_url(parent_key, value):
        return _redact_sensitive_url(str(value), parent_key)
    if isinstance(value, dict):
        return _normalize_map(value, parent_key)
    if isinstance(value, list):
        return [_normalize_value(item, parent_key) for item in value]
    return value


def _normalize_map(mapping: Mapping[Any, Any] | None, parent_key: str | None = None) -> dict[str, Any]:
    if mapping is None:
        return {}
    redacted = _redact_sensitive_map(mapping, parent_key)
    return {key: _normalize_value(redacted[key], key) for key in sorted(redacted)}


def _normalized_snapshot_field(field: str, value: Any) -> Any:
    if field == "functions":
        result: dict[str, Any] = {}
        for function in value or []:
            if isinstance(function, dict) and str(function.get("pluginId") or "").strip():
                result[str(function["pluginId"])] = _normalize_map(function.get("paramInfo") or {})
        return {key: result[key] for key in sorted(result)}
    if field == "contextProviders":
        return [_json_dump(_normalize_value(item), sort_keys=True) for item in value or [] if item is not None]
    if field in {"correctWordFileIds", "tagNames"}:
        return sorted(str(item) for item in value or [] if str(item).strip())
    if field == "summaryMemory":
        return "" if value is None or not str(value).strip() else str(value)
    return value


def _changed_snapshot_fields(current: dict[str, Any] | None, next_value: dict[str, Any] | None) -> list[str]:
    if next_value is None:
        return ["restore"]
    source = current or {}
    return [
        field
        for field in SNAPSHOT_FIELD_ORDER
        if _normalized_snapshot_field(field, source.get(field))
        != _normalized_snapshot_field(field, next_value.get(field))
    ]


def _snapshot_state_token(data: Mapping[str, Any]) -> str:
    normalized = {field: _normalized_snapshot_field(field, data.get(field)) for field in sorted(SNAPSHOT_FIELD_ORDER)}
    payload = _json_dump(normalized, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def run_chat_summary_task(session_id: str) -> None:
    async with get_session_factory()() as session:
        await AgentService(session).generate_chat_summary(session_id)


async def run_chat_title_task(session_id: str) -> None:
    async with get_session_factory()() as session:
        await AgentService(session).generate_chat_title(session_id)


async def _cancel_voiceprint_after_commit(voiceprint_id: str) -> None:
    try:
        async with get_session_factory()() as session:
            configured = await SystemParamService(session).get_value("server.voice_print", from_cache=True)
        client = VoicePrintClient(configured or "", timeout=get_settings().external_request_timeout_seconds)
        await client.cancel(voiceprint_id)
    except Exception:
        logger.exception("Unable to cancel external voiceprint %s after database deletion", voiceprint_id)


async def redact_legacy_agent_snapshots() -> int:
    """Worker-safe entry point for the legacy snapshot redaction job."""
    settings = get_settings()
    async with distributed_lock("jobs:agent-snapshot-redaction", settings.job_lock_ttl_seconds) as acquired:
        if not acquired:
            return 0
        async with get_session_factory()() as session:
            return await AgentService(session).redact_legacy_snapshots()
