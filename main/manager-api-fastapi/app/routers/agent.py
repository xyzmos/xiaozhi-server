from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.core.database import get_db
from app.core.errors import ErrorCode
from app.core.responses import JavaJSONResponse, error_response, ok
from app.core.security import AuthUser, require_normal, require_super_admin
from app.schemas.agent import (
    AgentChatHistoryReport,
    AgentCreate,
    AgentMemory,
    AgentSnapshotPage,
    AgentSnapshotRestore,
    AgentTagAssignment,
    AgentTemplate,
    AgentUpdate,
    AgentVoicePrintSave,
    AgentVoicePrintUpdate,
)
from app.services.agent import AgentService, run_chat_summary_task

router = APIRouter(tags=["agent"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
NormalUser = Annotated[AuthUser, Depends(require_normal)]
SuperUser = Annotated[AuthUser, Depends(require_super_admin)]


def _service(session: AsyncSession, user: AuthUser | None, request: Request) -> AgentService:
    return AgentService(session, user, language=request.headers.get("Accept-Language"))


@router.post("/agent/chat-history/report")
async def report_chat_history(report: AgentChatHistoryReport, request: Request, session: DbSession) -> JavaJSONResponse:
    return ok(await _service(session, None, request).report_chat(report))


@router.post("/agent/chat-history/getDownloadUrl/{agentId}/{sessionId}")
async def issue_chat_history_download(
    agentId: str, sessionId: str, request: Request, session: DbSession, user: NormalUser
) -> JavaJSONResponse:
    service = _service(session, user, request)
    if not await service.has_agent_permission(agentId):
        return error_response(request, 10132)
    return ok(await service.issue_history_token(agentId, sessionId))


@router.get("/agent/chat-history/download/{uuid}/current")
async def download_current_chat_history(uuid: str, request: Request, session: DbSession) -> Response:
    content = await _service(session, None, request).consume_history_download(uuid, previous=False)
    return Response(
        content.encode("utf-8"),
        media_type="text/plain;charset=UTF-8",
        headers={"Content-Disposition": "attachment;filename=history.txt"},
    )


@router.get("/agent/chat-history/download/{uuid}/previous")
async def download_previous_chat_history(uuid: str, request: Request, session: DbSession) -> Response:
    content = await _service(session, None, request).consume_history_download(uuid, previous=True)
    return Response(
        content.encode("utf-8"),
        media_type="text/plain;charset=UTF-8",
        headers={"Content-Disposition": "attachment;filename=history.txt"},
    )


# Static paths are deliberately registered before /agent/{id}; Starlette resolves in declaration order.
@router.get("/agent/template/page")
async def template_page(
    request: Request,
    session: DbSession,
    user: SuperUser,
    page: int = Query(default=1),
    limit: int = Query(default=10),
    agentName: str | None = Query(default=None),
) -> JavaJSONResponse:
    return ok(await _service(session, user, request).template_page(page, limit, agentName))


@router.post("/agent/template/batch-remove")
async def batch_delete_templates(
    ids: list[str], request: Request, session: DbSession, user: SuperUser
) -> JavaJSONResponse:
    deleted = await _service(session, user, request).batch_delete_templates(ids)
    return (
        ok("批量删除成功") if deleted else error_response(request, ErrorCode.INTERNAL_SERVER_ERROR, "批量删除模板失败")
    )


@router.get("/agent/template/{id}")
async def template_detail(id: str, request: Request, session: DbSession, user: SuperUser) -> JavaJSONResponse:
    result = await _service(session, user, request).template_detail(id)
    return ok(result) if result is not None else error_response(request, ErrorCode.INTERNAL_SERVER_ERROR, "模板不存在")


@router.post("/agent/template")
async def create_template(
    template: AgentTemplate, request: Request, session: DbSession, user: SuperUser
) -> JavaJSONResponse:
    return ok(await _service(session, user, request).create_template(template))


@router.put("/agent/template")
async def update_template(
    template: AgentTemplate, request: Request, session: DbSession, user: SuperUser
) -> JavaJSONResponse:
    # MyBatis-Plus raises before returning a boolean when updateById receives
    # an entity without its @TableId.  Keep Java's generic error envelope for
    # that exact input; an unknown but non-empty id still returns the controller's
    # explicit "更新模板失败" message below.
    if template.id is None:
        return error_response(request, ErrorCode.INTERNAL_SERVER_ERROR)
    updated = await _service(session, user, request).update_template(template)
    return ok(template) if updated else error_response(request, ErrorCode.INTERNAL_SERVER_ERROR, "更新模板失败")


@router.delete("/agent/template/{id}")
async def delete_template(id: str, request: Request, session: DbSession, user: SuperUser) -> JavaJSONResponse:
    service = _service(session, user, request)
    if await service.template_detail(id) is None:
        return error_response(request, ErrorCode.INTERNAL_SERVER_ERROR, "模板不存在")
    return (
        ok("删除模板成功")
        if await service.delete_template(id)
        else error_response(request, ErrorCode.INTERNAL_SERVER_ERROR, "删除模板失败")
    )


@router.post("/agent/voice-print")
async def create_voiceprint(
    dto: AgentVoicePrintSave, request: Request, session: DbSession, user: NormalUser
) -> JavaJSONResponse:
    created = await _service(session, user, request).create_voiceprint(dto)
    return ok() if created else error_response(request, 10057)


@router.put("/agent/voice-print")
async def update_voiceprint(
    dto: AgentVoicePrintUpdate, request: Request, session: DbSession, user: NormalUser
) -> JavaJSONResponse:
    updated = await _service(session, user, request).update_voiceprint(dto)
    return ok() if updated else error_response(request, 10058)


@router.delete("/agent/voice-print/{id}")
async def delete_voiceprint(id: str, request: Request, session: DbSession, user: NormalUser) -> JavaJSONResponse:
    deleted = await _service(session, user, request).delete_voiceprint(id)
    return ok() if deleted else error_response(request, 10059)


@router.get("/agent/voice-print/list/{id}")
async def list_voiceprints(id: str, request: Request, session: DbSession, user: NormalUser) -> JavaJSONResponse:
    return ok(await _service(session, user, request).voiceprint_list(id))


@router.get("/agent/mcp/address/{agentId}")
async def mcp_address(agentId: str, request: Request, session: DbSession, user: NormalUser) -> JavaJSONResponse:
    service = _service(session, user, request)
    if not await service.has_agent_permission(agentId):
        return error_response(request, 10200)
    address = await service.mcp_address(agentId)
    return ok(address) if address is not None else error_response(request, 10201)


@router.get("/agent/mcp/tools/{agentId}")
async def mcp_tools(agentId: str, request: Request, session: DbSession, user: NormalUser) -> JavaJSONResponse:
    service = _service(session, user, request)
    if not await service.has_agent_permission(agentId):
        return error_response(request, 10202)
    return ok(await service.mcp_tools(agentId))


@router.get("/agent/tag/list")
async def all_tags(request: Request, session: DbSession, user: NormalUser) -> JavaJSONResponse:
    return ok(await _service(session, user, request).all_tags())


@router.post("/agent/tag")
async def create_tag(
    request: Request,
    session: DbSession,
    user: NormalUser,
    params: dict[str, str] = Body(...),
) -> JavaJSONResponse:
    tag_name = params.get("tagName")
    if tag_name is None or not tag_name.strip():
        return error_response(request, ErrorCode.INTERNAL_SERVER_ERROR, "标签名称不能为空")
    return ok(await _service(session, user, request).save_tag(tag_name))


@router.delete("/agent/tag/{id}")
async def delete_tag(id: str, request: Request, session: DbSession, user: NormalUser) -> JavaJSONResponse:
    await _service(session, user, request).delete_tag(id)
    return ok()


@router.post("/agent/audio/{audioId}")
async def issue_audio_token(audioId: str, request: Request, session: DbSession, user: NormalUser) -> JavaJSONResponse:
    token = await _service(session, user, request).issue_audio_token(audioId)
    return ok(token) if token is not None else error_response(request, ErrorCode.INTERNAL_SERVER_ERROR, "音频不存在")


@router.get("/agent/play/{uuid}")
async def play_agent_audio(uuid: str, request: Request, session: DbSession) -> Response:
    audio = await _service(session, None, request).consume_audio_token(uuid)
    if audio is None:
        return Response(status_code=404)
    return Response(
        audio,
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="play.wav"'},
    )


@router.put("/agent/saveMemory/{macAddress}")
async def update_memory(
    macAddress: str, dto: AgentMemory, request: Request, session: DbSession, user: NormalUser
) -> JavaJSONResponse:
    await _service(session, user, request).update_memory_by_mac(macAddress, dto)
    return ok()


@router.post("/agent/chat-summary/{sessionId}/save")
async def save_chat_summary(
    sessionId: str, background_tasks: BackgroundTasks, request: Request, session: DbSession
) -> JavaJSONResponse:
    await _service(session, None, request).session_agent(sessionId)
    background_tasks.add_task(run_chat_summary_task, sessionId)
    return ok()


@router.post("/agent/chat-title/{sessionId}/generate")
async def generate_chat_title(sessionId: str, request: Request, session: DbSession) -> JavaJSONResponse:
    service = _service(session, None, request)
    await service.session_agent(sessionId)
    await service.generate_chat_title(sessionId)
    return ok()


@router.get("/agent/all")
async def admin_agent_list(
    request: Request,
    session: DbSession,
    user: SuperUser,
    page: int = Query(default=1),
    limit: int = Query(default=10),
    orderField: str | None = Query(default=None),
    order: str | None = Query(default=None),
) -> JavaJSONResponse:
    return ok(await _service(session, user, request).admin_agents(page, limit, orderField, order))


@router.get("/agent/list")
async def user_agent_list(
    request: Request,
    session: DbSession,
    user: NormalUser,
    keyword: str | None = Query(default=None),
    searchType: str = Query(default="name"),
) -> JavaJSONResponse:
    del searchType  # Java accepts the parameter but the consolidated implementation ignores it.
    return ok(await _service(session, user, request).user_agents(keyword))


@router.get("/agent/template")
async def template_list(request: Request, session: DbSession, user: NormalUser) -> JavaJSONResponse:
    return ok(await _service(session, user, request).templates())


@router.get("/agent/{agentId}/snapshots")
async def snapshot_page(
    agentId: str,
    request: Request,
    session: DbSession,
    user: NormalUser,
    page: int | None = Query(default=1),
    limit: int | None = Query(default=10),
    maxVersionNo: int | None = Query(default=None),
) -> JavaJSONResponse:
    params = AgentSnapshotPage(page=page, limit=limit, max_version_no=maxVersionNo)
    return ok(await _service(session, user, request).snapshot_page(agentId, params))


@router.get("/agent/{agentId}/snapshots/{snapshotId}")
async def snapshot_detail(
    agentId: str, snapshotId: str, request: Request, session: DbSession, user: NormalUser
) -> JavaJSONResponse:
    return ok(await _service(session, user, request).snapshot_detail(agentId, snapshotId))


@router.post("/agent/{agentId}/snapshots/{snapshotId}/restore")
async def restore_snapshot(
    agentId: str,
    snapshotId: str,
    dto: AgentSnapshotRestore,
    request: Request,
    session: DbSession,
    user: NormalUser,
) -> JavaJSONResponse:
    await _service(session, user, request).restore_snapshot(agentId, snapshotId, dto.current_state_token)
    return ok()


@router.delete("/agent/{agentId}/snapshots/{snapshotId}")
async def delete_snapshot(
    agentId: str, snapshotId: str, request: Request, session: DbSession, user: NormalUser
) -> JavaJSONResponse:
    await _service(session, user, request).delete_snapshot(agentId, snapshotId)
    return ok()


@router.get("/agent/{id}/sessions")
async def agent_sessions(
    id: str,
    request: Request,
    session: DbSession,
    user: NormalUser,
    page: str | None = Query(default=None),
    limit: str | None = Query(default=None),
) -> JavaJSONResponse:
    return ok(await _service(session, user, request).sessions(id, page, limit))


@router.get("/agent/{id}/chat-history/user")
async def recent_agent_history(id: str, request: Request, session: DbSession, user: NormalUser) -> JavaJSONResponse:
    service = _service(session, user, request)
    if not await service.has_agent_permission(id):
        return error_response(request, ErrorCode.INTERNAL_SERVER_ERROR, "没有权限查看该智能体的聊天记录")
    return ok(await service.recent_user_history(id))


@router.get("/agent/{id}/chat-history/audio")
async def agent_audio_content(id: str, request: Request, session: DbSession, user: NormalUser) -> JavaJSONResponse:
    return ok(await _service(session, user, request).audio_content(id))


@router.get("/agent/{id}/chat-history/{sessionId}")
async def agent_history(
    id: str, sessionId: str, request: Request, session: DbSession, user: NormalUser
) -> JavaJSONResponse:
    service = _service(session, user, request)
    if not await service.has_agent_permission(id):
        return error_response(request, ErrorCode.INTERNAL_SERVER_ERROR, "没有权限查看该智能体的聊天记录")
    return ok(await service.history(id, sessionId))


@router.get("/agent/{id}/tags")
async def agent_tags(id: str, request: Request, session: DbSession, user: NormalUser) -> JavaJSONResponse:
    return ok(await _service(session, user, request).agent_tags(id))


@router.put("/agent/{id}/tags")
async def save_agent_tags(
    id: str, dto: AgentTagAssignment, request: Request, session: DbSession, user: NormalUser
) -> JavaJSONResponse:
    await _service(session, user, request).save_agent_tags(id, dto.tag_ids, dto.tag_names)
    return ok()


@router.post("/agent")
async def create_agent(dto: AgentCreate, request: Request, session: DbSession, user: NormalUser) -> JavaJSONResponse:
    return ok(await _service(session, user, request).create_agent(dto))


@router.put("/agent/{id}")
async def update_agent(
    id: str, dto: AgentUpdate, request: Request, session: DbSession, user: NormalUser
) -> JavaJSONResponse:
    await _service(session, user, request).update_agent(id, dto)
    return ok()


@router.delete("/agent/{id}")
async def delete_agent(id: str, request: Request, session: DbSession, user: NormalUser) -> JavaJSONResponse:
    await _service(session, user, request).delete_agent(id)
    return ok()


@router.get("/agent/{id}")
async def agent_detail(id: str, request: Request, session: DbSession, user: NormalUser) -> JavaJSONResponse:
    return ok(await _service(session, user, request).agent_detail(id))
