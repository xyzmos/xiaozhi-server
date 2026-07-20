from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.core.database import get_db
from app.core.errors import AppError
from app.core.i18n import message_for
from app.core.responses import JavaJSONResponse, error_response, ok
from app.core.security import require_normal, require_super_admin
from app.schemas.voiceclone import VoiceCloneRenameRequest, VoiceCloneTrainRequest, VoiceResourceCreateRequest
from app.services.voiceclone import VoiceCloneService

voiceclone_router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(get_db)]
VoiceFile = Annotated[UploadFile, File(alias="voiceFile")]
VoiceIdForm = Annotated[str, Form(alias="id")]


def _query_map(request: Request) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in request.query_params.multi_items():
        if key in result:
            previous = result[key]
            result[key] = [*previous, value] if isinstance(previous, list) else [previous, value]
        else:
            result[key] = value
    return result


# Static voiceResource paths deliberately precede /voiceResource/{id}.
@voiceclone_router.get("/voiceResource/ttsPlatforms")
async def tts_platforms(
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(await VoiceCloneService(session).tts_platforms())


@voiceclone_router.get("/voiceResource/user/{user_id}")
async def voice_resources_by_user(
    user_id: int,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    require_normal(request)
    return ok(await VoiceCloneService(session).get_by_user(user_id))


@voiceclone_router.get("/voiceResource")
async def page_voice_resources(
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(await VoiceCloneService(session).page(_query_map(request)))


@voiceclone_router.get("/voiceResource/{voice_id}")
async def get_voice_resource(
    voice_id: str,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(await VoiceCloneService(session).get_detail(voice_id))


@voiceclone_router.post("/voiceResource")
async def create_voice_resource(
    request: Request,
    session: SessionDep,
    body: VoiceResourceCreateRequest | None = None,
) -> JavaJSONResponse:
    user = require_super_admin(request)
    if body is None:
        return error_response(request, 10145)
    if body.model_id is None or body.model_id == "":
        return error_response(request, 10146)
    if not body.voice_ids:
        return error_response(request, 10147)
    if body.user_id is None:
        return error_response(request, 10148)
    try:
        await VoiceCloneService(session).create_resources(body, actor=user)
        return ok()
    except AppError:
        raise
    except RuntimeError as exc:
        return error_response(request, 10065, str(exc))


@voiceclone_router.delete("/voiceResource/{voice_id}")
async def delete_voice_resource(
    voice_id: str,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    require_super_admin(request)
    ids = voice_id.split(",") if voice_id else []
    if not ids:
        return error_response(request, 10149)
    await VoiceCloneService(session).delete(ids)
    return ok()


@voiceclone_router.get("/voiceClone")
async def page_voice_clones(
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    return ok(await VoiceCloneService(session).page(_query_map(request), user_id=user.id))


@voiceclone_router.post("/voiceClone/upload")
async def upload_voice_clone(
    request: Request,
    session: SessionDep,
    voice_file: VoiceFile,
    voice_id: VoiceIdForm = "",
) -> JavaJSONResponse:
    user = require_normal(request)
    service = VoiceCloneService(session)
    try:
        content = await voice_file.read()
        if not content:
            return error_response(request, 10140)
        content_type = voice_file.content_type
        if content_type is None or not content_type.startswith("audio/"):
            return error_response(request, 10141)
        filename = voice_file.filename
        if filename is None or "." not in filename:
            raise RuntimeError("文件名缺少扩展名")
        extension = filename[filename.rfind(".") :].lower()
        if extension not in {".mp3", ".wav"}:
            return error_response(request, 500, "只允许上传.mp3和.wav格式的文件")
        if len(content) > 10 * 1024 * 1024:
            return error_response(request, 10142)
        await service.check_permission(voice_id, user)
        await service.upload_voice(voice_id, content)
        return ok()
    except Exception as exc:
        if isinstance(exc, AppError):
            message = exc.message or message_for(exc.code, request.headers.get("Accept-Language"))
        else:
            message = str(exc)
        return error_response(request, 10143, message)


@voiceclone_router.post("/voiceClone/updateName")
async def update_voice_clone_name(
    body: VoiceCloneRenameRequest,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    if body.id is None or body.id == "":
        return error_response(request, 10006)
    if body.name is None or body.name == "":
        return error_response(request, 10181)
    service = VoiceCloneService(session)
    try:
        await service.check_permission(body.id, user)
        await service.rename(body.id or "", body.name or "")
        return ok()
    except Exception as exc:
        if isinstance(exc, AppError):
            message = exc.message or message_for(exc.code, request.headers.get("Accept-Language"))
        else:
            message = str(exc)
        return error_response(request, 10066, message)


@voiceclone_router.post("/voiceClone/audio/{voice_id}")
async def get_voice_clone_audio_id(
    voice_id: str,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    service = VoiceCloneService(session)
    await service.check_permission(voice_id, user)
    return ok(await service.create_audio_id(voice_id))


@voiceclone_router.get("/voiceClone/play/{download_id}")
async def play_voice_clone(download_id: str, session: SessionDep) -> Response:
    try:
        content = await VoiceCloneService(session).consume_audio(download_id)
        if content is None:
            return Response(status_code=404)
        return Response(
            content,
            media_type="audio/wav",
            headers={
                "Content-Length": str(len(content)),
                "Content-Disposition": "inline; filename=voice.wav",
            },
        )
    except Exception:
        return Response(status_code=500)


@voiceclone_router.post("/voiceClone/cloneAudio")
async def train_voice_clone(
    body: VoiceCloneTrainRequest,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    service = VoiceCloneService(session)
    await service.check_permission(body.clone_id, user)
    await service.clone_audio(
        body.clone_id or "",
        accept_language=request.headers.get("Accept-Language"),
    )
    return ok()
