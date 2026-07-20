from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.responses import JavaJSONResponse, ok
from app.core.security import require_normal, require_super_admin
from app.repositories.timbre import TimbreRepository
from app.schemas.timbre import TimbreBody
from app.services.timbre import TimbreService

timbre_router = APIRouter()


def _service(session: AsyncSession) -> TimbreService:
    return TimbreService(TimbreRepository(session))


@timbre_router.get("/ttsVoice")
async def timbre_page(
    request: Request,
    tts_model_id: str | None = Query(default=None, alias="ttsModelId"),
    name: str | None = None,
    page: str | None = None,
    limit: str | None = None,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(
        await _service(session).page(
            tts_model_id, name, page, limit, request.headers.get("Accept-Language")
        )
    )


@timbre_router.post("/ttsVoice")
async def timbre_save(
    body: TimbreBody, request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    await _service(session).save(
        body, require_super_admin(request), request.headers.get("Accept-Language")
    )
    return ok()


@timbre_router.put("/ttsVoice/{timbre_id}")
async def timbre_update(
    timbre_id: str, body: TimbreBody, request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    await _service(session).update(
        timbre_id, body, require_super_admin(request), request.headers.get("Accept-Language")
    )
    return ok()


@timbre_router.post("/ttsVoice/delete")
async def timbre_delete(
    ids: list[str], request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    require_super_admin(request)
    await _service(session).delete(ids)
    return ok()


@timbre_router.get("/models/{model_id}/voices")
async def model_voices(
    model_id: str,
    request: Request,
    voice_name: str | None = Query(default=None, alias="voiceName"),
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    user = require_normal(request)
    return ok(await _service(session).voices(model_id, voice_name, user, request.headers.get("Accept-Language")))
