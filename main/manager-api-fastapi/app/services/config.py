from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import urllib.parse
from copy import deepcopy
from typing import Any, cast

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from redis.asyncio import Redis

from app.core.errors import AppError
from app.core.redis import JavaRedisCodec, get_redis
from app.repositories.config import ConfigRepository

logger = logging.getLogger(__name__)


class ConfigService:
    def __init__(self, repository: ConfigRepository, *, redis: Redis | None = None):
        self.repository = repository
        self.redis = redis or get_redis()

    async def get_config(self, *, use_cache: bool) -> dict[str, Any]:
        if use_cache:
            cached = JavaRedisCodec.decode(await cast(Any, self.redis.get)("server:config"))
            if isinstance(cached, dict):
                return cast(dict[str, Any], cached)
        result = self._build_base_config(await self.repository.list_params())
        template = await self.repository.get_default_template()
        if template is None:
            raise AppError(10183)
        await self._build_module_config(
            result=result,
            assistant_name=None,
            prompt=None,
            summary_memory=None,
            voice=None,
            reference_audio=None,
            reference_text=None,
            language=None,
            tts_volume=None,
            tts_rate=None,
            tts_pitch=None,
            vad_model_id=self._string(template.get("vad_model_id")),
            asr_model_id=self._string(template.get("asr_model_id")),
            llm_model_id=None,
            vllm_model_id=None,
            slm_model_id=None,
            tts_model_id=None,
            mem_model_id=None,
            intent_model_id=None,
            rag_model_id=None,
        )
        await cast(Any, self.redis.set)("server:config", JavaRedisCodec.encode(result), ex=24 * 60 * 60)
        return result

    async def get_agent_models(
        self,
        mac_address: str,
        selected_module: dict[str, str],
    ) -> dict[str, Any]:
        temporary_key = f"tmp_register_mac:{mac_address}"
        temporary = JavaRedisCodec.decode(await cast(Any, self.redis.get)(temporary_key))
        if temporary == "true":
            await cast(Any, self.redis.delete)(temporary_key)
            return await self.get_config(use_cache=True)

        device = await self.repository.get_device_by_mac(mac_address)
        if device is None:
            safe_address = mac_address.replace(":", "_").lower()
            activation = JavaRedisCodec.decode(
                await cast(Any, self.redis.get)(f"ota:activation:data:{safe_address}")
            )
            if isinstance(activation, dict) and activation.get("activation_code"):
                raise AppError(10042, params=(str(activation["activation_code"]),))
            raise AppError(10041)

        agent_id = self._string(device.get("agent_id"))
        agent = await self.repository.get_agent(agent_id or "") if agent_id else None
        if agent is None:
            raise AppError(10053)

        voice: str | None = None
        reference_audio: str | None = None
        reference_text: str | None = None
        language: str | None = None
        voice_id = self._string(agent.get("tts_voice_id"))
        timbre = await self._timbre(voice_id) if voice_id else None
        if timbre is not None:
            voice = self._string(timbre.get("tts_voice"))
            reference_audio = self._string(timbre.get("reference_audio"))
            reference_text = self._string(timbre.get("reference_text"))
            chosen_language = self._string(agent.get("tts_language"))
            if chosen_language and chosen_language.strip():
                language = chosen_language
            else:
                languages = self._string(timbre.get("languages"))
                if languages and languages.strip():
                    language = languages.split("、", 1)[0].strip()
        elif voice_id:
            clone = await self.repository.get_voice_clone(voice_id)
            if clone is not None:
                voice = self._string(clone.get("voice_id"))
                chosen_language = self._string(agent.get("tts_language"))
                language = chosen_language if chosen_language and chosen_language.strip() else "普通话"

        result: dict[str, Any] = {
            "device_max_output_size": await self._param("device_max_output_size", from_cache=True)
        }
        memory_model = self._string(agent.get("mem_model_id"))
        chat_history = agent.get("chat_history_conf")
        if memory_model == "Memory_nomem":
            chat_history = 0
        elif memory_model is not None and memory_model != "Memory_nomem" and chat_history is None:
            chat_history = 2
        result["chat_history_conf"] = chat_history

        vad_model_id = self._string(agent.get("vad_model_id"))
        asr_model_id = self._string(agent.get("asr_model_id"))
        if selected_module.get("VAD") == vad_model_id:
            vad_model_id = None
        if selected_module.get("ASR") == asr_model_id:
            asr_model_id = None

        if self._string(agent.get("intent_model_id")) != "Intent_nointent":
            plugins = await self._plugins(str(agent["id"]))
            if plugins:
                result["plugins"] = plugins

        mcp_endpoint = await self._mcp_address(str(agent["id"]))
        if mcp_endpoint and mcp_endpoint.startswith("ws"):
            result["mcp_endpoint"] = mcp_endpoint.replace("/mcp/", "/call/")

        context_providers = self._json_value(await self.repository.get_context_providers(str(agent["id"])))
        if isinstance(context_providers, list) and context_providers:
            result["context_providers"] = context_providers

        await self._add_voiceprint(str(agent["id"]), result)
        await self._build_module_config(
            result=result,
            assistant_name=self._string(agent.get("agent_name")),
            prompt=self._string(agent.get("system_prompt")),
            summary_memory=self._string(agent.get("summary_memory")),
            voice=voice,
            reference_audio=reference_audio,
            reference_text=reference_text,
            language=language,
            tts_volume=self._integer(agent.get("tts_volume")),
            tts_rate=self._integer(agent.get("tts_rate")),
            tts_pitch=self._integer(agent.get("tts_pitch")),
            vad_model_id=vad_model_id,
            asr_model_id=asr_model_id,
            llm_model_id=self._string(agent.get("llm_model_id")),
            vllm_model_id=self._string(agent.get("vllm_model_id")),
            slm_model_id=self._string(agent.get("slm_model_id")),
            tts_model_id=self._string(agent.get("tts_model_id")),
            mem_model_id=memory_model,
            intent_model_id=self._string(agent.get("intent_model_id")),
            rag_model_id=None,
        )
        return result

    async def get_correct_words(self, mac_address: str) -> list[str]:
        device = await self.repository.get_device_by_mac(mac_address)
        if device is None or device.get("agent_id") is None:
            return []
        rows = await self.repository.get_correct_word_items(str(device["agent_id"]))
        return [
            f"{self._java_string(row.get('source_word'))}|{self._java_string(row.get('target_word'))}"
            for row in rows
        ]

    @staticmethod
    def _build_base_config(rows: list[dict[str, Any]]) -> dict[str, Any]:
        config: dict[str, Any] = {}
        for row in rows:
            code = str(row.get("param_code") or "")
            keys = code.split(".")
            current = config
            for key in keys[:-1]:
                if key not in current:
                    current[key] = {}
                nested = current[key]
                if not isinstance(nested, dict):
                    raise TypeError(f"configuration path {code} collides with scalar key {key}")
                current = nested
            value = str(row.get("param_value") or "")
            value_type = str(row.get("value_type") or "string").lower()
            current[keys[-1]] = ConfigService._typed_param(value, value_type)
        return config

    @staticmethod
    def _typed_param(value: str, value_type: str) -> Any:
        if value_type == "number":
            try:
                number = float(value)
                # Java's implementation returns an Integer only when the double
                # equals its narrowing conversion to a signed 32-bit int.
                if math.isnan(number):
                    narrowed = 0
                elif number >= 2**31 - 1:
                    narrowed = 2**31 - 1
                elif number <= -(2**31):
                    narrowed = -(2**31)
                else:
                    narrowed = int(number)
                return narrowed if number == narrowed else number
            except ValueError:
                return value
        if value_type == "boolean":
            return value.lower() == "true"
        if value_type == "array":
            return [item.strip() for item in value.split(";") if item.strip()]
        if value_type == "json":
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    async def _build_module_config(
        self,
        *,
        result: dict[str, Any],
        assistant_name: str | None,
        prompt: str | None,
        summary_memory: str | None,
        voice: str | None,
        reference_audio: str | None,
        reference_text: str | None,
        language: str | None,
        tts_volume: int | None,
        tts_rate: int | None,
        tts_pitch: int | None,
        vad_model_id: str | None,
        asr_model_id: str | None,
        llm_model_id: str | None,
        vllm_model_id: str | None,
        slm_model_id: str | None,
        tts_model_id: str | None,
        mem_model_id: str | None,
        intent_model_id: str | None,
        rag_model_id: str | None,
    ) -> None:
        selected: dict[str, str] = {}
        model_types = ("VAD", "ASR", "TTS", "Memory", "Intent", "LLM", "VLLM", "SLM", "RAG")
        model_ids = (
            vad_model_id,
            asr_model_id,
            tts_model_id,
            mem_model_id,
            intent_model_id,
            llm_model_id,
            vllm_model_id,
            slm_model_id,
            rag_model_id,
        )
        intent_llm_id: str | None = None
        memory_llm_id: str | None = None
        for model_type, model_id in zip(model_types, model_ids, strict=True):
            if model_id is None:
                continue
            model = await self._model(model_id)
            if model is None:
                continue
            configuration = self._json_value(model.get("config_json"))
            type_config: dict[str, Any] = {}
            if isinstance(configuration, dict):
                configuration = deepcopy(configuration)
                type_config[str(model["id"])] = configuration
                if model_type == "TTS":
                    optional_values = {
                        "private_voice": voice,
                        "ref_audio": reference_audio,
                        "ref_text": reference_text,
                        "language": language,
                        "ttsVolume": tts_volume,
                        "ttsRate": tts_rate,
                        "ttsPitch": tts_pitch,
                    }
                    configuration.update({key: value for key, value in optional_values.items() if value is not None})
                    if configuration.get("type") == "huoshan_double_stream" and voice and voice.startswith("S_"):
                        configuration["resource_id"] = "seed-icl-1.0"
                elif model_type == "Intent":
                    if configuration.get("type") == "intent_llm":
                        intent_llm_id = self._string(configuration.get("llm"))
                        if intent_llm_id == llm_model_id:
                            intent_llm_id = None
                    functions = configuration.get("functions")
                    if isinstance(functions, str) and functions.strip():
                        configuration["functions"] = functions.split(";")
                elif model_type == "Memory" and configuration.get("type") == "mem_local_short":
                    memory_llm_id = self._string(configuration.get("llm"))
                    if memory_llm_id == llm_model_id:
                        memory_llm_id = None
                elif model_type == "LLM":
                    for extra_id in (intent_llm_id, memory_llm_id):
                        if extra_id and extra_id not in type_config:
                            extra = await self._model(extra_id)
                            if extra is not None:
                                type_config[str(extra["id"])] = deepcopy(self._json_value(extra.get("config_json")))
                    if slm_model_id and slm_model_id != llm_model_id and slm_model_id not in type_config:
                        small = await self._model(slm_model_id)
                        small_config = None if small is None else self._json_value(small.get("config_json"))
                        if small is not None and small_config is not None:
                            type_config[str(small["id"])] = deepcopy(small_config)
            result[model_type] = type_config
            selected[model_type] = str(model["id"])
        result["selected_module"] = selected
        if prompt and prompt.strip():
            replacement = assistant_name if assistant_name and assistant_name.strip() else "小智"
            prompt = prompt.replace("{{assistant_name}}", replacement)
        result["prompt"] = prompt
        result["summaryMemory"] = summary_memory

    async def _plugins(self, agent_id: str) -> dict[str, Any]:
        mappings = await self.repository.get_plugin_mappings(agent_id)
        result: dict[str, Any] = {}
        knowledge_groups: dict[str, list[dict[str, Any]]] = {}
        knowledge_models: dict[str, dict[str, Any]] = {}
        for mapping in mappings:
            provider_code = self._string(mapping.get("provider_code"))
            if provider_code and provider_code.strip():
                value = mapping.get("param_info")
                result[provider_code] = (
                    json.dumps(value, ensure_ascii=False, separators=(",", ":")) if isinstance(value, dict) else value
                )
        # Java removes knowledge mappings by iterating the original list backwards, which reverses dataset order.
        for mapping in reversed(mappings):
            provider_code = self._string(mapping.get("provider_code"))
            if provider_code and provider_code.strip():
                continue
            dataset = await self.repository.get_dataset(str(mapping["plugin_id"]))
            if dataset is None or dataset.get("rag_model_id") is None:
                continue
            model = await self._model(str(dataset["rag_model_id"]))
            if model is None or not model.get("model_code"):
                continue
            code = str(model["model_code"])
            knowledge_groups.setdefault(code, []).append(dataset)
            knowledge_models[code] = model
        for code, datasets in knowledge_groups.items():
            model_config = self._json_value(knowledge_models[code].get("config_json"))
            if not isinstance(model_config, dict):
                continue
            names = ",".join(self._java_string(dataset.get("name")) for dataset in datasets)
            descriptions = ",".join(
                self._java_string(dataset.get("description")) for dataset in datasets
            )
            params = {
                "base_url": model_config.get("base_url"),
                "api_key": model_config.get("api_key"),
                "dataset_ids": [dataset.get("dataset_id") for dataset in datasets],
                "description": (
                    f"如果用户询问与【{names}】涵盖的主体范围相关内容时应调用本方法，"
                    f"用于查询：{descriptions}"
                ),
            }
            result[f"search_from_{code}"] = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
        return result

    async def _mcp_address(self, agent_id: str) -> str | None:
        endpoint = await self._param("server.mcp_endpoint", from_cache=True)
        if endpoint is None or not endpoint.strip() or endpoint == "null":
            return None
        parsed = urllib.parse.urlsplit(endpoint)
        query = parsed.query
        marker_index = query.find("key=")
        key = query[marker_index + len("key=") :]
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = parsed.path
        prefix_path = path[: path.rfind("/")] if "/" in path else ""
        prefix = urllib.parse.urlunsplit((scheme, parsed.netloc, prefix_path, "", ""))
        token = self._aes_encrypt(
            key,
            json.dumps(
                {"agentId": hashlib.md5(agent_id.encode(), usedforsecurity=False).hexdigest()},
                ensure_ascii=False,
                separators=(", ", ": "),
            ),
        )
        return f"{prefix}/mcp/?token={urllib.parse.quote_plus(token)}"

    @staticmethod
    def _aes_encrypt(key: str, plaintext: str) -> str:
        key_bytes = key.encode()
        if len(key_bytes) not in {16, 24, 32}:
            key_bytes = (key_bytes + bytes(32))[:32]
        block_size = 16
        padding_length = block_size - len(plaintext.encode()) % block_size
        padded = plaintext.encode() + bytes([padding_length]) * padding_length
        # Java's published MCP token format is AES/ECB/PKCS5Padding; changing modes breaks existing servers.
        encryptor = Cipher(algorithms.AES(key_bytes), modes.ECB()).encryptor()  # noqa: S305
        encrypted = encryptor.update(padded) + encryptor.finalize()
        return base64.b64encode(encrypted).decode("ascii")

    async def _add_voiceprint(self, agent_id: str, result: dict[str, Any]) -> None:
        try:
            url = await self._param("server.voice_print", from_cache=True)
            if url is None or not url.strip() or url == "null":
                return
            rows = await self.repository.get_voiceprints(agent_id)
            if not rows:
                return
            speakers = [
                (
                    f"{self._java_string(row.get('id'))},"
                    f"{self._java_string(row.get('source_name'))},{row.get('introduce') or ''}"
                )
                for row in rows
            ]
            threshold_value = await self._param("server.voiceprint_similarity_threshold", from_cache=True)
            try:
                threshold = (
                    float(threshold_value)
                    if threshold_value is not None and threshold_value not in ("", "null")
                    else 0.4
                )
            except ValueError:
                threshold = 0.4
            result["voiceprint"] = {"url": url, "speakers": speakers, "similarity_threshold": threshold}
        except Exception:
            logger.warning("Voiceprint configuration lookup failed", exc_info=True)

    async def _param(self, code: str, *, from_cache: bool) -> str | None:
        if from_cache:
            cached = JavaRedisCodec.decode(await cast(Any, self.redis.hget)("sys:params", code))
            if cached is not None:
                return str(cached)
        value = await self.repository.get_param_value(code)
        if value is not None and from_cache:
            await cast(Any, self.redis.hset)("sys:params", code, JavaRedisCodec.encode(value))
            await cast(Any, self.redis.expire)("sys:params", 24 * 60 * 60)
        return value

    async def _model(self, model_id: str) -> dict[str, Any] | None:
        key = f"model:data:{model_id}"
        cached = JavaRedisCodec.decode(await cast(Any, self.redis.get)(key))
        if isinstance(cached, dict):
            return self._normalize_cached(cast(dict[str, Any], cached))
        model = await self.repository.get_model(model_id)
        if model is not None:
            raw_configuration = model.get("config_json")
            if isinstance(raw_configuration, str):
                parsed_configuration = json.loads(raw_configuration)
                if parsed_configuration is not None and not isinstance(parsed_configuration, dict):
                    raise TypeError("ModelConfigEntity.configJson must be a JSON object")
                model["config_json"] = parsed_configuration
            await cast(Any, self.redis.set)(
                key,
                JavaRedisCodec.encode(
                    model,
                    java_type="xiaozhi.modules.model.entity.ModelConfigEntity",
                    field_java_types={
                        "configJson": "cn.hutool.json.JSONObject",
                        "creator": "java.lang.Long",
                        "updater": "java.lang.Long",
                    },
                ),
                ex=24 * 60 * 60,
            )
        return model

    async def _timbre(self, timbre_id: str) -> dict[str, Any] | None:
        key = f"timbre:details:{timbre_id}"
        cached = JavaRedisCodec.decode(await cast(Any, self.redis.get)(key))
        if isinstance(cached, dict):
            return self._normalize_cached(cast(dict[str, Any], cached))
        timbre = await self.repository.get_timbre(timbre_id)
        if timbre is not None:
            await cast(Any, self.redis.set)(
                key,
                JavaRedisCodec.encode(
                    timbre,
                    java_type="xiaozhi.modules.timbre.vo.TimbreDetailsVO",
                    field_java_types={"sort": "java.lang.Long"},
                ),
                ex=24 * 60 * 60,
            )
        return timbre

    @staticmethod
    def _normalize_cached(value: dict[str, Any]) -> dict[str, Any]:
        aliases = {
            "modelType": "model_type",
            "modelCode": "model_code",
            "modelName": "model_name",
            "configJson": "config_json",
            "ttsVoice": "tts_voice",
            "referenceAudio": "reference_audio",
            "referenceText": "reference_text",
            "ttsModelId": "tts_model_id",
        }
        return {aliases.get(key, key): item for key, item in value.items() if key != "@class"}

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, bytes):
            value = value.decode()
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    @staticmethod
    def _string(value: Any) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def _integer(value: Any) -> int | None:
        return None if value is None else int(value)

    @staticmethod
    def _java_string(value: Any) -> str:
        return "null" if value is None else str(value)
