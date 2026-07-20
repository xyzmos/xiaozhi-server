from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.core.database import get_db
from app.core.responses import JavaJSONResponse, ok
from app.core.security import require_normal
from app.repositories.correctword import CorrectWordRepository
from app.schemas.correctword import CorrectWordFileBody
from app.services.correctword import CorrectWordService

correctword_router = APIRouter()


def _java_urlencode(value: str) -> str:
    # java.net.URLEncoder leaves alphanumerics plus .-*_ unescaped, encodes
    # spaces as '+', and encodes '~'.  The controller then replaces '+' with
    # '%20'.  urllib always leaves '~', so handle that final difference here.
    return quote(value, safe="*.-_").replace("~", "%7E")


def _service(session: AsyncSession) -> CorrectWordService:
    return CorrectWordService(CorrectWordRepository(session))


@correctword_router.post("/correct-word/file")
async def create_file(
    body: CorrectWordFileBody, request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    return ok(await _service(session).create(body, require_normal(request)))


@correctword_router.put("/correct-word/file/{file_id}")
async def update_file(
    file_id: str,
    body: CorrectWordFileBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    await _service(session).update(file_id, body, require_normal(request))
    return ok()


@correctword_router.get("/correct-word/file/list")
async def list_files(
    request: Request,
    page: str | None = None,
    limit: str | None = None,
    session: AsyncSession = Depends(get_db),
) -> JavaJSONResponse:
    return ok(await _service(session).page(require_normal(request), page, limit))


@correctword_router.get("/correct-word/file/select")
async def select_files(request: Request, session: AsyncSession = Depends(get_db)) -> JavaJSONResponse:
    return ok(await _service(session).all(require_normal(request)))


@correctword_router.get("/correct-word/file/download/{file_id}")
async def download_file(
    file_id: str, request: Request, session: AsyncSession = Depends(get_db)
) -> Response:
    require_normal(request)
    item = await _service(session).get(file_id)
    if item is None or not item["content"]:
        return Response(status_code=404)
    body = "\n".join(item["content"]).encode("utf-8")
    file_name = str(item["fileName"])
    ascii_name = "".join(character if ord(character) < 128 else "_" for character in file_name)
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{_java_urlencode(file_name)}"
    return Response(
        body,
        media_type="application/octet-stream",
        headers={"Content-Disposition": disposition, "Content-Length": str(len(body))},
    )


@correctword_router.delete("/correct-word/file/{file_id}")
async def delete_file(
    file_id: str, request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    require_normal(request)
    await _service(session).delete([file_id])
    return ok()


@correctword_router.post("/correct-word/file/batch-delete")
async def batch_delete_files(
    file_ids: list[str], request: Request, session: AsyncSession = Depends(get_db)
) -> JavaJSONResponse:
    require_normal(request)
    await _service(session).delete(file_ids)
    return ok()
