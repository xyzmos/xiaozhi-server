from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.responses import JavaJSONResponse, envelope, ok
from app.core.security import require_normal, require_super_admin
from app.repositories.config import ConfigRepository
from app.repositories.model import ModelRepository
from app.schemas.model import ModelConfigBody, ModelProviderBody
from app.services.config import ConfigService
from app.services.model import ModelProviderService, ModelService

model_router = APIRouter()


def _models(session: AsyncSession) -> ModelService:
    return ModelService(ModelRepository(session))


def _providers(session: AsyncSession) -> ModelProviderService:
    return ModelProviderService(ModelRepository(session))


async def _refresh_server_config(session: AsyncSession) -> None:
    await ConfigService(ConfigRepository(session)).get_config(use_cache=False)


@model_router.get("/models/names")
async def model_names(
    request: Request,
    model_type: str = Query(alias="modelType"),
    model_name: str | None = Query(default=None, alias="modelName"),
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_normal(request)
    return ok(await _models(session).names(model_type, model_name))


@model_router.get("/models/llm/names")
async def llm_names(
    request: Request,
    model_name: str | None = Query(default=None, alias="modelName"),
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_normal(request)
    return ok(await _models(session).llm_names(model_name))


@model_router.get("/models/list")
async def model_list(
    request: Request,
    model_type: str = Query(alias="modelType"),
    model_name: str | None = Query(default=None, alias="modelName"),
    page: str = "0",
    limit: str = "10",
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(await _models(session).model_page(model_type, model_name, page, limit))


@model_router.get("/models/provider/plugin/names")
async def plugin_names(request: Request, session: AsyncSession = Depends(get_db)) -> JavaJSONResponse:
    user = require_normal(request)
    return ok(await ModelRepository(session).list_plugins_for_user(user.id))


@model_router.get("/models/provider")
async def provider_list(
    request: Request,
    model_type: str | None = Query(default=None, alias="modelType"),
    name: str | None = None,
    page: str = "0",
    limit: str = "10",
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(await _providers(session).page(model_type, name, page, limit))


@model_router.post("/models/provider")
async def provider_add(
    body: ModelProviderBody, request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    return ok(await _providers(session).add(body, require_super_admin(request)))


@model_router.put("/models/provider")
async def provider_edit(
    body: ModelProviderBody, request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    return ok(await _providers(session).edit(body, require_super_admin(request)))


@model_router.post("/models/provider/delete")
async def provider_delete(
    ids: list[str], request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    require_super_admin(request)
    await _providers(session).delete(ids)
    return ok()


@model_router.get("/models/{model_type}/provideTypes")
async def provider_types(
    model_type: str, request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(await ModelRepository(session).list_providers_by_type(model_type))


@model_router.post("/models/{model_type}/{provide_code}")
async def model_add(
    model_type: str,
    provide_code: str,
    body: ModelConfigBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    result = await _models(session).add(model_type, provide_code, body)
    await _refresh_server_config(session)
    return ok(result)


@model_router.put("/models/enable/{model_id}/{status}")
async def model_enable(
    model_id: str, status: int, request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    require_super_admin(request)
    message = await _models(session).enable(model_id, status)
    return JavaJSONResponse(envelope(None, code=500, msg=message)) if message else ok()


@model_router.put("/models/{model_type}/{provide_code}/{model_id}")
async def model_edit(
    model_type: str,
    provide_code: str,
    model_id: str,
    body: ModelConfigBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    result = await _models(session).edit(model_type, provide_code, model_id, body)
    await _refresh_server_config(session)
    return ok(result)


@model_router.put("/models/default/{model_id}")
async def model_default(
    model_id: str, request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    require_super_admin(request)
    message = await _models(session).set_default(model_id)
    if message:
        return JavaJSONResponse(envelope(None, code=500, msg=message))
    await _refresh_server_config(session)
    return ok()


@model_router.get("/models/{model_id}")
async def model_get(
    model_id: str, request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(await _models(session).get_model(model_id))


@model_router.delete("/models/{model_id}")
async def model_delete(
    model_id: str, request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    require_super_admin(request)
    await _models(session).delete(model_id)
    return ok()
