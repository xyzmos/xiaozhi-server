from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator
from pydantic_core import PydanticCustomError

from app.schemas.common import JavaModel


class AgentCreate(JavaModel):
    agent_name: str

    @field_validator("agent_name", mode="before")
    @classmethod
    def require_non_blank_name(cls, value: Any) -> Any:
        if value is None or isinstance(value, str) and not value.strip():
            raise PydanticCustomError("java_not_blank", "智能体名称不能为空")
        return value


class AgentMemory(JavaModel):
    summary_memory: str | None = None


class ContextProvider(JavaModel):
    url: str | None = None
    headers: dict[str, Any] | None = None


class FunctionInfo(JavaModel):
    plugin_id: str | None = None
    param_info: dict[str, Any] = Field(default_factory=dict)

    @field_validator("param_info", mode="before")
    @classmethod
    def normalize_param_info(cls, value: Any) -> dict[str, Any]:
        if value is None or value == "":
            return {}
        if isinstance(value, str):
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise ValueError("paramInfo must be a JSON object")
            return {str(key): item for key, item in parsed.items()}
        if isinstance(value, dict):
            return {str(key): item for key, item in value.items() if key is not None}
        parsed = json.loads(json.dumps(value))
        if not isinstance(parsed, dict):
            raise ValueError("paramInfo must be an object")
        return {str(key): item for key, item in parsed.items()}


class AgentUpdate(JavaModel):
    agent_code: str | None = None
    agent_name: str | None = None
    asr_model_id: str | None = None
    vad_model_id: str | None = None
    llm_model_id: str | None = None
    slm_model_id: str | None = None
    vllm_model_id: str | None = None
    tts_model_id: str | None = None
    tts_voice_id: str | None = None
    tts_language: str | None = None
    tts_volume: int | None = None
    tts_rate: int | None = None
    tts_pitch: int | None = None
    mem_model_id: str | None = None
    intent_model_id: str | None = None
    functions: list[FunctionInfo] | None = None
    system_prompt: str | None = None
    summary_memory: str | None = None
    chat_history_conf: int | None = None
    lang_code: str | None = None
    language: str | None = None
    sort: int | None = None
    context_providers: list[ContextProvider] | None = None
    correct_word_file_ids: list[str] | None = None
    tag_names: list[str] | None = None
    tag_ids: list[str] | None = None


class AgentChatHistoryReport(JavaModel):
    mac_address: str
    session_id: str
    chat_type: int
    content: str
    audio_base64: str | None = None
    report_time: int | None = None

    @field_validator("mac_address", "session_id", "content", mode="before")
    @classmethod
    def require_non_blank(cls, value: Any) -> Any:
        if value is None or isinstance(value, str) and not value.strip():
            raise PydanticCustomError("java_not_blank", "不能为空")
        return value

    @field_validator("chat_type", mode="before")
    @classmethod
    def require_chat_type(cls, value: Any) -> Any:
        if value is None:
            raise PydanticCustomError("java_not_null", "不能为空")
        return value


class AgentSnapshotPage(JavaModel):
    page: int | None = 1
    limit: int | None = 10
    max_version_no: int | None = None

    def page_or_default(self) -> int:
        return self.page if self.page is not None and self.page >= 1 else 1

    def limit_or_default(self) -> int:
        return self.limit if self.limit is not None and self.limit >= 1 else 10


class AgentSnapshotRestore(JavaModel):
    current_state_token: str

    @field_validator("current_state_token", mode="before")
    @classmethod
    def require_non_blank_token(cls, value: Any) -> Any:
        if value is None or isinstance(value, str) and not value.strip():
            raise PydanticCustomError("java_not_blank", "不能为空")
        return value


class AgentSnapshotTag(JavaModel):
    id: str | None = None
    tag_name: str | None = None
    sort: int | None = None


class AgentSnapshotData(JavaModel):
    agent_code: str | None = None
    agent_name: str | None = None
    asr_model_id: str | None = None
    vad_model_id: str | None = None
    llm_model_id: str | None = None
    slm_model_id: str | None = None
    vllm_model_id: str | None = None
    tts_model_id: str | None = None
    tts_voice_id: str | None = None
    tts_language: str | None = None
    tts_volume: int | None = None
    tts_rate: int | None = None
    tts_pitch: int | None = None
    mem_model_id: str | None = None
    intent_model_id: str | None = None
    chat_history_conf: int | None = None
    system_prompt: str | None = None
    summary_memory: str | None = None
    lang_code: str | None = None
    language: str | None = None
    sort: int | None = None
    functions: list[FunctionInfo] | None = None
    context_providers: list[ContextProvider] | None = None
    correct_word_file_ids: list[str] | None = None
    tag_names: list[str] | None = None
    tags: list[AgentSnapshotTag] | None = None


class AgentTemplate(JavaModel):
    id: str | None = None
    agent_code: str | None = None
    agent_name: str | None = None
    asr_model_id: str | None = None
    vad_model_id: str | None = None
    llm_model_id: str | None = None
    vllm_model_id: str | None = None
    tts_model_id: str | None = None
    tts_voice_id: str | None = None
    tts_language: str | None = None
    tts_volume: int | None = None
    tts_rate: int | None = None
    tts_pitch: int | None = None
    mem_model_id: str | None = None
    intent_model_id: str | None = None
    chat_history_conf: int | None = None
    system_prompt: str | None = None
    summary_memory: str | None = None
    lang_code: str | None = None
    language: str | None = None
    sort: int | None = None
    creator: int | None = None
    created_at: datetime | None = None
    updater: int | None = None
    updated_at: datetime | None = None


class AgentVoicePrintSave(JavaModel):
    agent_id: str | None = None
    audio_id: str | None = None
    source_name: str | None = None
    introduce: str | None = None


class AgentVoicePrintUpdate(JavaModel):
    id: str | None = None
    audio_id: str | None = None
    source_name: str | None = None
    introduce: str | None = None


class AgentTagAssignment(JavaModel):
    tag_ids: list[str] | None = None
    tag_names: list[str] | None = None


SNAPSHOT_FIELD_ORDER = [
    "agentCode",
    "agentName",
    "asrModelId",
    "vadModelId",
    "llmModelId",
    "slmModelId",
    "vllmModelId",
    "ttsModelId",
    "ttsVoiceId",
    "ttsLanguage",
    "ttsVolume",
    "ttsRate",
    "ttsPitch",
    "memModelId",
    "intentModelId",
    "chatHistoryConf",
    "systemPrompt",
    "summaryMemory",
    "langCode",
    "language",
    "sort",
    "functions",
    "contextProviders",
    "correctWordFileIds",
    "tagNames",
]
