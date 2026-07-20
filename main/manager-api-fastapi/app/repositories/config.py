from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Repository


class ConfigRepository(Repository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def list_params(self) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT param_code, param_value, value_type FROM sys_params WHERE param_type = 1"
        )

    async def get_param_value(self, code: str) -> str | None:
        value = await self.scalar(
            "SELECT param_value FROM sys_params WHERE param_code = :code LIMIT 1",
            {"code": code},
        )
        return None if value is None else str(value)

    async def get_default_template(self) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT id, agent_code, agent_name, asr_model_id, vad_model_id, llm_model_id, "
            "vllm_model_id, tts_model_id, tts_voice_id, tts_language, tts_volume, tts_rate, tts_pitch, "
            "mem_model_id, intent_model_id, chat_history_conf, system_prompt, summary_memory, lang_code, "
            "language, sort FROM ai_agent_template ORDER BY sort ASC LIMIT 1"
        )

    async def get_device_by_mac(self, mac_address: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT id, user_id, mac_address, board, agent_id, app_version, auto_update "
            "FROM ai_device WHERE mac_address = :mac_address LIMIT 1",
            {"mac_address": mac_address},
        )

    async def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT id, user_id, agent_code, agent_name, asr_model_id, vad_model_id, llm_model_id, slm_model_id, "
            "vllm_model_id, tts_model_id, tts_voice_id, tts_language, tts_volume, tts_rate, tts_pitch, "
            "mem_model_id, intent_model_id, chat_history_conf, system_prompt, summary_memory, lang_code, language "
            "FROM ai_agent WHERE id = :id LIMIT 1",
            {"id": agent_id},
        )

    async def get_model(self, model_id: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT id, model_type, model_code, model_name, is_default, is_enabled, config_json, doc_link, "
            "remark, sort, creator, create_date, updater, update_date "
            "FROM ai_model_config WHERE id = :id LIMIT 1",
            {"id": model_id},
        )

    async def get_timbre(self, timbre_id: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT id, languages, name, remark, reference_audio, reference_text, sort, tts_model_id, "
            "tts_voice, voice_demo FROM ai_tts_voice WHERE id = :id LIMIT 1",
            {"id": timbre_id},
        )

    async def get_voice_clone(self, clone_id: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT id, name, model_id, voice_id, languages, user_id, train_status, train_error "
            "FROM ai_voice_clone WHERE id = :id LIMIT 1",
            {"id": clone_id},
        )

    async def get_plugin_mappings(self, agent_id: str) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT m.id, m.agent_id, m.plugin_id, m.param_info, "
            "(SELECT p.provider_code FROM ai_model_provider p WHERE p.id = m.plugin_id LIMIT 1) AS provider_code "
            "FROM ai_agent_plugin_mapping m WHERE m.agent_id = :agent_id",
            {"agent_id": agent_id},
        )

    async def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            "SELECT id, dataset_id, rag_model_id, name, description, status "
            "FROM ai_rag_dataset WHERE id = :id LIMIT 1",
            {"id": dataset_id},
        )

    async def get_context_providers(self, agent_id: str) -> Any:
        return await self.scalar(
            "SELECT context_providers FROM ai_agent_context_provider WHERE agent_id = :agent_id LIMIT 1",
            {"agent_id": agent_id},
        )

    async def get_voiceprints(self, agent_id: str) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT id, agent_id, source_name, introduce, create_date "
            "FROM ai_agent_voice_print WHERE agent_id = :agent_id ORDER BY create_date ASC",
            {"agent_id": agent_id},
        )

    async def get_correct_word_items(self, agent_id: str) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT i.source_word, i.target_word FROM ai_agent_correct_word_mapping m "
            "JOIN ai_agent_correct_word_item i ON i.file_id = m.file_id WHERE m.agent_id = :agent_id",
            {"agent_id": agent_id},
        )
