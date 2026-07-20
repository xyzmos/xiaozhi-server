# ruff: noqa: B008
# FastAPI evaluates dependency and body marker defaults intentionally when registering routes.
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.responses import JavaJSONResponse, envelope, ok
from app.core.security import require_normal, require_super_admin
from app.repositories.sys import SysRepository
from app.schemas.sys import DictDataPayload, DictTypePayload, EmitServerActionRequest, SysParamPayload
from app.services.sys import AdminService, DictService, ServerActionService, SysParamService

sys_router = APIRouter()


def _repository(session: AsyncSession) -> SysRepository:
    return SysRepository(session)


def _admin(session: AsyncSession) -> AdminService:
    return AdminService(_repository(session))


def _params(session: AsyncSession) -> SysParamService:
    return SysParamService(_repository(session))


def _dict(session: AsyncSession) -> DictService:
    return DictService(_repository(session))


async def _refresh_server_config(session: AsyncSession) -> None:
    from app.repositories.config import ConfigRepository
    from app.services.config import ConfigService

    await ConfigService(ConfigRepository(session)).get_config(use_cache=False)


@sys_router.get("/admin/users")
async def page_users(
    request: Request,
    mobile: str | None = None,
    page: str = Query(default="1"),
    limit: str = Query(default="10"),
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    try:
        current, size = int(page), int(limit)
    except ValueError as exc:
        # Java parses these Map-backed values inside the service; malformed
        # numbers therefore reach its generic code=500 handler rather than
        # Bean Validation.
        raise AppError(500, "排序值不能小于0") from exc
    return ok(await _admin(session).page_users(mobile=mobile, page=current, limit=size))


@sys_router.put("/admin/users/{user_id}")
async def reset_user_password(
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    user = require_super_admin(request)
    return ok(await _admin(session).reset_password(user_id, user))


@sys_router.delete("/admin/users/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    await _admin(session).delete_user(user_id)
    return ok()


@sys_router.put("/admin/users/changeStatus/{status}")
async def change_user_status(
    status: int,
    request: Request,
    user_ids: list[str] = Body(),
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    user = require_super_admin(request)
    await _admin(session).change_status(status, user_ids, user)
    return ok()


@sys_router.get("/admin/device/all")
async def page_all_devices(
    request: Request,
    keywords: str | None = None,
    page: int = Query(default=1, ge=0),
    limit: int = Query(default=10, ge=0),
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(await _admin(session).page_devices(keywords=keywords, page=page, limit=limit))


@sys_router.get("/admin/server/server-list")
async def websocket_server_list(request: Request, session: AsyncSession = Depends(get_db)) -> JavaJSONResponse:
    require_super_admin(request)
    params = _params(session)
    return ok(await ServerActionService(params).server_list())


@sys_router.post("/admin/server/emit-action")
async def emit_server_action(
    dto: EmitServerActionRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(await ServerActionService(_params(session)).emit(dto))


@sys_router.get("/admin/params/page")
async def page_params(
    request: Request,
    page: int = Query(default=1, ge=0),
    limit: int = Query(default=10, ge=0),
    order_field: str | None = Query(default=None, alias="orderField"),
    order: str | None = None,
    param_code: str | None = Query(default=None, alias="paramCode"),
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(
        await _params(session).page(
            param_code=param_code,
            page=page,
            limit=limit,
            order_field=order_field,
            order=order,
        )
    )


@sys_router.get("/admin/params/{param_id}")
async def get_param(
    param_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(await _params(session).get(param_id))


@sys_router.post("/admin/params")
async def save_param(
    dto: SysParamPayload,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    await _params(session).save(
        dto,
        require_super_admin(request),
        request.headers.get("Accept-Language"),
    )
    await _refresh_server_config(session)
    return ok()


@sys_router.put("/admin/params")
async def update_param(
    dto: SysParamPayload,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    await _params(session).update(
        dto,
        require_super_admin(request),
        request.headers.get("Accept-Language"),
    )
    await _refresh_server_config(session)
    return ok()


@sys_router.post("/admin/params/delete")
async def delete_params(
    request: Request,
    ids: list[str] = Body(),
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    await _params(session).delete(ids)
    await _refresh_server_config(session)
    return ok()


@sys_router.get("/admin/dict/type/page")
async def page_dict_types(
    request: Request,
    dict_type: str | None = Query(default=None, alias="dictType"),
    dict_name: str | None = Query(default=None, alias="dictName"),
    page: int = Query(default=1, ge=0),
    limit: int = Query(default=10, ge=0),
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(
        await _dict(session).page_types(
            dict_type=dict_type,
            dict_name=dict_name,
            page=page,
            limit=limit,
        )
    )


@sys_router.get("/admin/dict/type/{type_id}")
async def get_dict_type(
    type_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(await _dict(session).get_type(type_id))


@sys_router.post("/admin/dict/type/save")
async def save_dict_type(
    dto: DictTypePayload,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    await _dict(session).save_type(dto, require_super_admin(request))
    return ok()


@sys_router.put("/admin/dict/type/update")
async def update_dict_type(
    dto: DictTypePayload,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    await _dict(session).update_type(dto, require_super_admin(request))
    return ok()


@sys_router.post("/admin/dict/type/delete")
async def delete_dict_types(
    request: Request,
    ids: list[int] = Body(),
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    await _dict(session).delete_types(ids)
    return ok()


@sys_router.get("/admin/dict/data/page")
async def page_dict_data(
    request: Request,
    dict_type_id: str | None = Query(default=None, alias="dictTypeId"),
    dict_label: str | None = Query(default=None, alias="dictLabel"),
    dict_value: str | None = Query(default=None, alias="dictValue"),
    page: int = Query(default=1, ge=0),
    limit: int = Query(default=10, ge=0),
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    if dict_type_id is None or not dict_type_id:
        return JavaJSONResponse(envelope(None, code=500, msg="dictTypeId不能为空"))
    try:
        parsed_type_id = int(dict_type_id)
    except ValueError as exc:
        raise AppError(500) from exc
    return ok(
        await _dict(session).page_data(
            dict_type_id=parsed_type_id,
            dict_label=dict_label,
            dict_value=dict_value,
            page=page,
            limit=limit,
        )
    )


@sys_router.get("/admin/dict/data/type/{dict_type}")
async def dict_items(
    dict_type: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_normal(request)
    return ok(await _dict(session).items(dict_type))


@sys_router.get("/admin/dict/data/{data_id}")
async def get_dict_data(
    data_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    return ok(await _dict(session).get_data(data_id))


@sys_router.post("/admin/dict/data/save")
async def save_dict_data(
    dto: DictDataPayload,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    await _dict(session).save_data(dto, require_super_admin(request))
    return ok()


@sys_router.put("/admin/dict/data/update")
async def update_dict_data(
    dto: DictDataPayload,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    await _dict(session).update_data(dto, require_super_admin(request))
    return ok()


@sys_router.post("/admin/dict/data/delete")
async def delete_dict_data(
    request: Request,
    ids: list[int] = Body(),
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    require_super_admin(request)
    await _dict(session).delete_data(ids)
    return ok()
