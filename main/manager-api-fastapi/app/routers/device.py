from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.core.database import get_db
from app.core.i18n import resolve_language
from app.core.responses import JavaJSONResponse, envelope, error_response, ok
from app.core.security import require_normal, require_super_admin
from app.schemas.device import (
    DeviceAddressBookAliasRequest,
    DeviceAddressBookPermissionRequest,
    DeviceManualAddRequest,
    DeviceRegisterRequest,
    DeviceReportRequest,
    DeviceToolCallRequest,
    DeviceUnbindRequest,
    DeviceUpdateRequest,
    OtaRecord,
)
from app.services.device import MAC_PATTERN, DeviceService, is_blank

device_router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(get_db)]
FirmwareUpload = Annotated[UploadFile, File()]
CallerMacQuery = Annotated[str, Query(alias="callerMac")]
DeviceIdHeader = Annotated[str | None, Header(alias="Device-Id")]
ClientIdHeader = Annotated[str | None, Header(alias="Client-Id")]


def _query_map(request: Request) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in request.query_params.multi_items():
        if key in result:
            previous = result[key]
            result[key] = [*previous, value] if isinstance(previous, list) else [previous, value]
        else:
            result[key] = value
    return result


def _raw_ota(payload: dict[str, Any]) -> Response:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return Response(
        body,
        status_code=200,
        media_type="application/json",
        headers={"Content-Length": str(len(body))},
    )


@device_router.post("/device/bind/{agent_id}/{device_code}")
async def bind_device(
    agent_id: str,
    device_code: str,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    await DeviceService(session).activate_bound_device(agent_id=agent_id, activation_code=device_code, user=user)
    return ok()


@device_router.post("/device/register")
async def register_device(
    body: DeviceRegisterRequest,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    require_normal(request)
    if is_blank(body.mac_address):
        return error_response(request, 10175)
    return ok(await DeviceService(session).register_device(body.mac_address or ""))


@device_router.get("/device/bind/{agent_id}")
async def get_bound_devices(
    agent_id: str,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    return ok(await DeviceService(session).list_user_devices(user.id, agent_id))


@device_router.post("/device/bind/{agent_id}")
async def device_online(
    agent_id: str,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    await request.body()
    try:
        return ok(await DeviceService(session).get_online_data(agent_id, user))
    except Exception as exc:
        return error_response(request, 500, f"转发请求失败: {exc}")


@device_router.post("/device/unbind")
async def unbind_device(
    body: DeviceUnbindRequest,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    # DeviceController does not apply @Valid to DeviceUnBindDTO.  An empty
    # object reaches the service with a null id and is a successful no-op.
    await DeviceService(session).unbind(user_id=user.id, device_id=body.device_id or "")
    return ok()


@device_router.put("/device/update/{device_id}")
async def update_device(
    device_id: str,
    body: DeviceUpdateRequest,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    validation = _validate_device_update(body, request.headers.get("Accept-Language"))
    if validation is not None:
        return error_response(request, 10034, validation)
    if not await DeviceService(session).update_device(device_id=device_id, request=body, user=user):
        return error_response(request, 500, "设备不存在")
    return ok()


@device_router.put("/user/configDevice/{device_id}")
async def configure_device(
    device_id: str,
    body: DeviceUpdateRequest,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    validation = _validate_device_update(body, request.headers.get("Accept-Language"))
    if validation is not None:
        return error_response(request, 10034, validation)
    if not await DeviceService(session).update_device(device_id=device_id, request=body, user=user):
        return error_response(request, 500, "设备不存在")
    return ok()


@device_router.post("/device/manual-add")
async def manual_add_device(
    body: DeviceManualAddRequest,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    await DeviceService(session).manual_add(request=body, user=user)
    return ok()


@device_router.post("/device/tools/list/{device_id}")
async def list_device_tools(
    device_id: str,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    tools = await DeviceService(session).get_tools(device_id=device_id, user=user)
    if tools is None:
        return error_response(request, 10194)
    return ok(tools)


@device_router.post("/device/tools/call/{device_id}")
async def call_device_tool(
    device_id: str,
    body: DeviceToolCallRequest,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    if is_blank(body.name):
        return error_response(request, 10034, "工具名称不能为空")
    result = await DeviceService(session).call_tool(
        device_id=device_id,
        tool_name=body.name or "",
        arguments=body.arguments,
        user=user,
    )
    if result is None:
        return error_response(request, 10194)
    return JavaJSONResponse(envelope(result, msg="Tools called successfully"))


# Static address-book paths deliberately precede /address-book/{mac_address}.
@device_router.get("/device/address-book/call")
async def call_address_book(
    request: Request,
    session: SessionDep,
    caller_mac: CallerMacQuery,
    nickname: str,
    answer: bool = False,
) -> JavaJSONResponse:
    result = await DeviceService(session).call_by_nickname(
        caller_mac=caller_mac,
        nickname=nickname,
        answer=answer,
    )
    return ok(result)


@device_router.get("/device/address-book/lookup")
async def lookup_address_book(
    request: Request,
    session: SessionDep,
    caller_mac: CallerMacQuery,
    nickname: str,
) -> JavaJSONResponse:
    result = await DeviceService(session).lookup_address_book(caller_mac=caller_mac, nickname=nickname)
    if result is None:
        return error_response(request, 500, "未找到对应设备")
    return ok(result)


@device_router.put("/device/address-book/alias")
async def update_address_alias(
    body: DeviceAddressBookAliasRequest,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    if is_blank(body.target_mac):
        return error_response(request, 10034, "目标MAC地址不能为空")
    if is_blank(body.mac_address):
        return error_response(request, 10034, "MAC地址不能为空")
    service = DeviceService(session)
    caller = await service.repository.get_device_by_mac(body.mac_address or "")
    if caller is None or int(caller.get("user_id") or -1) != user.id:
        return error_response(request, 500, "无权限操作该设备")
    await service.save_address_book(
        mac_address=body.mac_address or "",
        target_mac=body.target_mac or "",
        alias=body.alias,
        has_permission=None,
        actor=user.id,
    )
    return ok()


@device_router.put("/device/address-book/permission")
async def update_address_permission(
    body: DeviceAddressBookPermissionRequest,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    if is_blank(body.mac_address):
        return error_response(request, 10034, "MAC地址不能为空")
    if is_blank(body.target_mac):
        return error_response(request, 10034, "目标MAC地址不能为空")
    service = DeviceService(session)
    caller = await service.repository.get_device_by_mac(body.mac_address or "")
    if caller is None or int(caller.get("user_id") or -1) != user.id:
        return error_response(request, 500, "无权限操作该设备")
    await service.save_address_book(
        mac_address=body.mac_address or "",
        target_mac=body.target_mac or "",
        alias=None,
        has_permission=body.has_permission,
        actor=user.id,
    )
    return ok()


@device_router.get("/device/address-book/{mac_address}")
async def get_address_book(
    mac_address: str,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    require_normal(request)
    return ok(await DeviceService(session).address_book(mac_address))


@device_router.post("/ota/")
async def check_ota_version(
    report: DeviceReportRequest,
    request: Request,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    device_id: DeviceIdHeader = None,
    client_id: ClientIdHeader = None,
) -> Response:
    if is_blank(device_id):
        # Java's required @RequestHeader fails before the controller's blank
        # guard and is translated by its global handler into this envelope.
        return error_response(request, 500)
    if MAC_PATTERN.fullmatch(device_id or "") is None:
        return _raw_ota({"error": "Invalid device ID"})
    selected_client = device_id if is_blank(client_id) else client_id
    client_ip = request.client.host if request.client is not None else "unknown"
    service = DeviceService(session)

    def defer_connection_update(device: str, agent: str | None, version: str | None) -> None:
        background_tasks.add_task(
            DeviceService.persist_connection_update_background,
            device,
            agent,
            version,
        )

    payload = await service.check_ota(
        device_id=device_id or "",
        client_id=selected_client or device_id or "",
        report=report,
        request_url=str(request.url),
        client_ip=client_ip,
        defer_connection_update=defer_connection_update,
    )
    return _raw_ota(payload)


@device_router.post("/ota/activate")
async def activate_ota_device(
    request: Request,
    session: SessionDep,
    device_id: DeviceIdHeader = None,
    client_id: ClientIdHeader = None,
) -> Response:
    del client_id
    if is_blank(device_id):
        return error_response(request, 500)
    if await DeviceService(session).repository.get_device_by_mac(device_id or "") is None:
        return Response(status_code=202)
    return Response("success", media_type="text/plain;charset=UTF-8")


@device_router.get("/ota/")
async def ota_health(session: SessionDep) -> Response:
    return Response(
        await DeviceService(session).ota_health_text(),
        media_type="text/plain;charset=UTF-8",
    )


# Static otaMag paths deliberately precede /otaMag/{id}.
@device_router.get("/otaMag/getDownloadUrl/{ota_id}")
async def get_ota_download_url(
    ota_id: str,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(await DeviceService(session).create_ota_download_id(ota_id))


@device_router.get("/otaMag/download/{download_id}")
async def download_ota(download_id: str, session: SessionDep) -> Response:
    resolved = await DeviceService(session).resolve_ota_download(download_id)
    if resolved is None:
        return Response(status_code=404)
    path, filename = resolved
    try:
        content = path.read_bytes()
    except OSError:
        return Response(status_code=500)
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content)),
        },
    )


@device_router.post("/otaMag/upload")
async def upload_firmware(
    request: Request,
    file: FirmwareUpload,
    session: SessionDep,
) -> JavaJSONResponse:
    require_super_admin(request)
    service = DeviceService(session)
    try:
        content = await file.read()
        return ok(await service.save_firmware_file(filename=file.filename, content=content))
    except ValueError as exc:
        return error_response(request, 500, str(exc))
    except OSError as exc:
        return error_response(request, 500, f"文件上传失败：{exc}")


@device_router.post("/otaMag/uploadAssetsBin")
async def upload_assets_firmware(
    request: Request,
    file: FirmwareUpload,
    session: SessionDep,
) -> JavaJSONResponse:
    user = require_normal(request)
    service = DeviceService(session)
    try:
        content = await file.read()
        return ok(await service.save_assets_file(filename=file.filename, content=content, user=user))
    except ValueError as exc:
        return error_response(request, 500, str(exc))
    except OSError as exc:
        return error_response(request, 500, f"文件上传失败：{exc}")


@device_router.get("/otaMag")
async def page_ota(
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(await DeviceService(session).ota_page(_query_map(request)))


@device_router.get("/otaMag/{ota_id}")
async def get_ota(
    ota_id: str,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(await DeviceService(session).get_ota_record(ota_id))


@device_router.post("/otaMag")
async def save_ota(
    request: Request,
    session: SessionDep,
    record: OtaRecord | None = None,
) -> JavaJSONResponse:
    user = require_super_admin(request)
    if record is None:
        return error_response(request, 500, "固件信息不能为空")
    if is_blank(record.firmware_name):
        return error_response(request, 500, "固件名称不能为空")
    if is_blank(record.type):
        return error_response(request, 500, "固件类型不能为空")
    if is_blank(record.version):
        return error_response(request, 500, "版本号不能为空")
    try:
        await DeviceService(session).save_ota(record, user)
        return ok()
    except RuntimeError as exc:
        return error_response(request, 500, str(exc))


@device_router.delete("/otaMag/{ota_id}")
async def delete_ota(
    ota_id: str,
    request: Request,
    session: SessionDep,
) -> JavaJSONResponse:
    require_super_admin(request)
    ids = ota_id.split(",") if ota_id else []
    if not ids:
        return error_response(request, 500, "删除的固件ID不能为空")
    await DeviceService(session).delete_ota(ids)
    return ok()


@device_router.put("/otaMag/{ota_id}")
async def update_ota(
    ota_id: str,
    request: Request,
    session: SessionDep,
    record: OtaRecord | None = None,
) -> JavaJSONResponse:
    user = require_super_admin(request)
    if record is None:
        return error_response(request, 500, "固件信息不能为空")
    try:
        await DeviceService(session).update_ota(ota_id, record, user)
        return ok()
    except RuntimeError as exc:
        return error_response(request, 500, str(exc))


def _validate_device_update(body: DeviceUpdateRequest, accept_language: str | None) -> str | None:
    language = resolve_language(accept_language)
    if body.auto_update is not None and body.auto_update < 0:
        return {
            "zh-CN": "最小不能小于0",
            "zh-TW": "必須大於或等於 0",
            "de-DE": "muss größer-gleich 0 sein",
            "pt-BR": "deve ser maior que ou igual à 0",
        }.get(language, "must be greater than or equal to 0")
    if body.auto_update is not None and body.auto_update > 1:
        return {
            "zh-CN": "最大不能超过1",
            "zh-TW": "必須小於或等於 1",
            "de-DE": "muss kleiner-gleich 1 sein",
            "pt-BR": "deve ser menor que ou igual à 1",
        }.get(language, "must be less than or equal to 1")
    if body.alias is not None and len(body.alias.encode("utf-16-le")) // 2 > 64:
        return {
            "zh-CN": "个数必须在0和64之间",
            "zh-TW": "大小必須在 0 和 64 之間",
            "de-DE": "Größe muss zwischen 0 und 64 sein",
            "pt-BR": "tamanho deve ser entre 0 e 64",
        }.get(language, "size must be between 0 and 64")
    return None
