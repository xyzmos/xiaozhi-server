# ruff: noqa: B008
# FastAPI evaluates dependency marker defaults intentionally when registering routes.
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.responses import JavaJSONResponse, ok
from app.core.serialization import preserve_java_map_keys
from app.repositories.config import ConfigRepository
from app.schemas.config import AgentModelsRequest, CorrectWordsRequest
from app.services.config import ConfigService

config_router = APIRouter()


def _service(session: AsyncSession) -> ConfigService:
    return ConfigService(ConfigRepository(session))


@config_router.post("/config/server-base")
async def server_base(session: AsyncSession = Depends(get_db)) -> JavaJSONResponse:
    return ok(preserve_java_map_keys(await _service(session).get_config(use_cache=True)))


@config_router.post("/config/agent-models")
async def agent_models(dto: AgentModelsRequest, session: AsyncSession = Depends(get_db)) -> JavaJSONResponse:
    return ok(preserve_java_map_keys(await _service(session).get_agent_models(dto.mac_address, dto.selected_module)))


@config_router.post("/config/correct-words")
async def correct_words(dto: CorrectWordsRequest, session: AsyncSession = Depends(get_db)) -> JavaJSONResponse:
    return ok(await _service(session).get_correct_words(dto.mac_address))
