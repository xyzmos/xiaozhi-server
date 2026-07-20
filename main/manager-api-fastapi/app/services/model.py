from __future__ import annotations

import copy
import json
import uuid
from typing import Any

from app.core.errors import AppError
from app.core.redis import get_redis
from app.core.security import AuthUser, shanghai_now_naive
from app.repositories.model import ModelRepository, parse_json_object
from app.schemas.model import ModelConfigBody, ModelProviderBody

SENSITIVE_FIELDS = {
    "api_key",
    "personal_access_token",
    "access_token",
    "token",
    "secret",
    "access_key_secret",
    "secret_key",
}


def _mask_middle(value: str) -> str:
    if not value.strip() or len(value) == 1:
        return value
    if len(value) <= 8:
        return value[:2] + "****" + value[-2:]
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def mask_sensitive(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key.lower() in SENSITIVE_FIELDS and isinstance(item, str):
            result[key] = _mask_middle(item)
        elif isinstance(item, dict):
            result[key] = mask_sensitive(item)
        else:
            result[key] = copy.deepcopy(item)
    return result


def _merge_config(original: dict[str, Any], updated: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(original)
    for key, value in updated.items():
        if key.lower() in SENSITIVE_FIELDS:
            if isinstance(value, str) and "****" not in value:
                result[key] = value
        elif isinstance(value, dict):
            child = result.get(key)
            result[key] = _merge_config(child if isinstance(child, dict) else {}, value)
        else:
            result[key] = copy.deepcopy(value)
    for key in list(result):
        if key not in updated and key.lower() not in SENSITIVE_FIELDS:
            del result[key]
    return result


def _model_dto(row: dict[str, Any], *, masked: bool = True) -> dict[str, Any]:
    config = parse_json_object(row.get("config_json"))
    return {
        "id": row.get("id"),
        "modelType": row.get("model_type"),
        "modelCode": row.get("model_code"),
        "modelName": row.get("model_name"),
        "isDefault": row.get("is_default"),
        "isEnabled": row.get("is_enabled"),
        "configJson": mask_sensitive(config) if masked else config,
        "docLink": row.get("doc_link"),
        "remark": row.get("remark"),
        "sort": row.get("sort"),
    }


class ModelService:
    def __init__(self, repository: ModelRepository):
        self.repository = repository

    async def names(self, model_type: str, model_name: str | None) -> list[dict[str, Any]]:
        return [
            {"id": row.get("id"), "modelName": row.get("model_name")}
            for row in await self.repository.list_model_names(model_type, model_name)
        ]

    async def llm_names(self, model_name: str | None) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in await self.repository.list_llm_names(model_name):
            config = parse_json_object(row.get("config_json")) or {}
            result.append(
                {"id": row.get("id"), "modelName": row.get("model_name"), "type": str(config.get("type", ""))}
            )
        return result

    async def model_page(self, model_type: str, model_name: str | None, page: str, limit: str) -> dict[str, Any]:
        current, size = max(int(page), 1), int(limit)
        rows, total = await self.repository.list_model_configs(
            model_type=model_type,
            model_name=model_name,
            offset=(current - 1) * size,
            limit=size,
        )
        return {"total": total, "list": [_model_dto(row) for row in rows]}

    async def get_model(self, model_id: str) -> dict[str, Any] | None:
        row = await self.repository.get_model(model_id)
        return _model_dto(row) if row else None

    async def add(self, model_type: str, provider_code: str, body: ModelConfigBody) -> dict[str, Any]:
        if not model_type.strip() or not provider_code.strip():
            raise AppError(10131)
        model_id = body.id or uuid.uuid4().hex
        values = {
            "id": model_id,
            "model_type": model_type,
            "model_code": body.model_code,
            "model_name": body.model_name,
            "is_default": 0,
            "is_enabled": body.is_enabled,
            "config_json": json.dumps(body.config_json, ensure_ascii=False) if body.config_json is not None else None,
            "doc_link": body.doc_link,
            "remark": body.remark,
            "sort": body.sort,
        }
        async with self.repository.session.begin():
            # Keep the read and write in one transaction.  A query before
            # ``begin()`` triggers SQLAlchemy autobegin and makes the explicit
            # transaction fail with InvalidRequestError.
            if await self.repository.get_provider(model_type, provider_code) is None:
                raise AppError(10162)
            await self.repository.insert_model(values)
        return _model_dto(values)

    async def edit(
        self, model_type: str, provider_code: str, model_id: str, body: ModelConfigBody
    ) -> dict[str, Any]:
        if not model_type.strip() or not provider_code.strip():
            raise AppError(10131)
        async with self.repository.session.begin():
            if await self.repository.get_provider(model_type, provider_code) is None:
                raise AppError(10162)
            original = await self.repository.get_model(model_id, for_update=True)
            if original is None:
                raise AppError(10051)
            updated_config = body.config_json
            if updated_config is not None and "llm" in updated_config:
                llm = await self.repository.get_model(str(updated_config["llm"]))
                llm_config = parse_json_object(llm.get("config_json")) if llm else None
                if llm is None or str(llm.get("model_type") or "").upper() != "LLM":
                    raise AppError(10092)
                if llm_config and "type" in llm_config and llm_config["type"] not in {"openai", "ollama"}:
                    raise AppError(10049)
            original_config = parse_json_object(original.get("config_json"))
            merged = (
                _merge_config(original_config, updated_config)
                if original_config is not None and updated_config is not None
                else original_config
            )
            values = {
                "id": model_id,
                "model_type": model_type,
                "model_code": original.get("model_code"),
                "model_name": body.model_name,
                "is_default": original.get("is_default"),
                "is_enabled": body.is_enabled,
                "config_json": json.dumps(merged, ensure_ascii=False) if merged is not None else None,
                "doc_link": original.get("doc_link"),
                "remark": body.remark,
                "sort": body.sort,
            }
            await self.repository.update_model(values)
        await self._clear_cache(model_id)
        return _model_dto(values)

    async def delete(self, model_id: str) -> None:
        if not model_id.strip():
            raise AppError(10006)
        async with self.repository.session.begin():
            model = await self.repository.get_model(model_id, for_update=True)
            if model and int(model.get("is_default") or 0) == 1:
                raise AppError(10064)
            agents = await self.repository.model_agent_references(model_id)
            if agents:
                raise AppError(10093, params=("、".join(agents),))
            if model and str(model.get("model_type") or "").upper() == "LLM":
                if await self.repository.intent_reference_count(model_id):
                    raise AppError(10094)
            await self.repository.delete_model(model_id)
        await self._clear_cache(model_id)

    async def enable(self, model_id: str, status: int) -> str | None:
        async with self.repository.session.begin():
            model = await self.repository.get_model(model_id, for_update=True)
            if model is None:
                return "模型配置不存在"
            if status == 0 and int(model.get("is_default") or 0) > 0:
                return "默认模型配置不允许关闭"
            await self.repository.set_model_enabled(model_id, status)
        await self._clear_cache(model_id)
        return None

    async def set_default(self, model_id: str) -> str | None:
        async with self.repository.session.begin():
            model = await self.repository.get_model(model_id, for_update=True)
            if model is None:
                return "模型配置不存在"
            model_type = str(model.get("model_type") or "")
            await self.repository.set_models_default(model_type, 0)
            await self.repository.execute(
                "UPDATE ai_model_config SET is_enabled=1, is_default=1 WHERE id=:id", {"id": model_id}
            )
            await self.repository.update_default_template_models(model_type, model_id)
        await self._clear_type_cache(model_type)
        return None

    async def _clear_cache(self, model_id: str) -> None:
        redis = get_redis()
        await redis.delete(f"model:data:{model_id}", f"model:name:{model_id}")

    async def _clear_type_cache(self, model_type: str) -> None:
        rows = await self.repository.fetch_all(
            "SELECT id FROM ai_model_config WHERE model_type=:type", {"type": model_type}
        )
        if rows:
            redis = get_redis()
            keys = [key for row in rows for key in (f"model:data:{row['id']}", f"model:name:{row['id']}")]
            await redis.delete(*keys)


class ModelProviderService:
    def __init__(self, repository: ModelRepository):
        self.repository = repository

    async def page(
        self, model_type: str | None, name: str | None, page: str, limit: str
    ) -> dict[str, Any]:
        current, size = max(int(page), 1), int(limit)
        rows, total = await self.repository.list_providers(
            model_type=model_type, name=name, offset=(current - 1) * size, limit=size
        )
        return {"total": total, "list": rows}

    @staticmethod
    def _validate(body: ModelProviderBody, *, update: bool) -> None:
        if update and (body.id is None or not body.id.strip()):
            raise AppError(10034, "id不能为空")
        for field, message in (
            (body.provider_code, "providerCode不能为空"),
            (body.model_type, "modelType不能为空"),
            (body.name, "name不能为空"),
            (body.fields, "fields(JSON格式)不能为空"),
        ):
            if field is None or not field.strip():
                raise AppError(10034, message)
        if body.sort is None:
            raise AppError(10034, "sort不能为空")

    async def add(self, body: ModelProviderBody, user: AuthUser) -> dict[str, Any]:
        self._validate(body, update=False)
        now = shanghai_now_naive()
        values = {
            "id": body.id or uuid.uuid4().hex,
            "model_type": body.model_type,
            "provider_code": body.provider_code,
            "name": body.name,
            "fields": body.fields,
            "sort": body.sort,
            "creator": user.id,
            "updater": user.id,
            "now": now,
        }
        async with self.repository.session.begin():
            await self.repository.insert_provider(values)
        return {
            # The Java service returns the request DTO, not the entity on which
            # MyBatis-Plus generated the UUID.  Therefore an omitted id remains
            # null in the response even though the stored row has an id.
            "id": body.id, "modelType": body.model_type, "providerCode": body.provider_code,
            "name": body.name, "fields": body.fields, "sort": body.sort, "creator": user.id,
            "updater": user.id, "createDate": now, "updateDate": now,
        }

    async def edit(self, body: ModelProviderBody, user: AuthUser) -> dict[str, Any]:
        self._validate(body, update=True)
        now = shanghai_now_naive()
        values = {
            "id": body.id, "model_type": body.model_type, "provider_code": body.provider_code,
            "name": body.name, "fields": body.fields, "sort": body.sort, "updater": user.id, "now": now,
        }
        async with self.repository.session.begin():
            if await self.repository.update_provider(values) == 0:
                raise AppError(10066)
        return {
            "id": body.id, "modelType": body.model_type, "providerCode": body.provider_code,
            "name": body.name, "fields": body.fields, "sort": body.sort, "updater": user.id,
            "updateDate": now, "creator": None, "createDate": None,
        }

    async def delete(self, ids: list[str]) -> None:
        async with self.repository.session.begin():
            if await self.repository.delete_providers(ids) == 0:
                raise AppError(10043)
