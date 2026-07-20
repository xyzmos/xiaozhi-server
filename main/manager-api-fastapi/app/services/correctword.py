from __future__ import annotations

import uuid
from typing import Any

from app.core.errors import AppError
from app.core.security import AuthUser, shanghai_now_naive
from app.repositories.correctword import CorrectWordRepository
from app.schemas.correctword import CorrectWordFileBody


def _parse_lines(lines: list[str]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for raw in lines:
        line = raw.strip()
        if not line or "|" not in line:
            continue
        source, target = line.split("|", 1)
        if source.strip() and target.strip():
            result.append((source.strip(), target.strip()))
    return result


def _content_lines(value: str | None) -> list[str]:
    if value is None:
        return []
    # Java String.split keeps one empty element for the empty source string,
    # while still discarding trailing empty elements for non-empty strings.
    if value == "":
        return [""]
    lines = value.split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def file_vo(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "fileName": row.get("file_name"),
        "wordCount": row.get("word_count"),
        "content": _content_lines(row.get("content")),
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


class CorrectWordService:
    def __init__(self, repository: CorrectWordRepository):
        self.repository = repository

    @staticmethod
    def validate(body: CorrectWordFileBody, *, check_size: bool) -> None:
        if body.file_name is None or not body.file_name.strip():
            raise AppError(10034, "文件名不能为空")
        if not body.content:
            raise AppError(10034, "替换词内容不能为空")
        if check_size and body.file_size is not None and body.file_size > 1024 * 1024:
            raise AppError(10204)

    async def create(self, body: CorrectWordFileBody, user: AuthUser) -> dict[str, Any]:
        self.validate(body, check_size=True)
        assert body.file_name is not None
        assert body.content is not None
        items = _parse_lines(body.content)
        file_id, now = uuid.uuid4().hex, shanghai_now_naive()
        values = {
            "id": file_id,
            "file_name": body.file_name,
            "word_count": len(items),
            "content": "\n".join(body.content),
            "creator": user.id,
            "now": now,
        }
        async with self.repository.session.begin():
            if await self.repository.name_exists(user.id, body.file_name):
                raise AppError(10203)
            await self.repository.insert_file(values)
            await self.repository.insert_items(
                [
                    {"id": uuid.uuid4().hex, "file_id": file_id, "source_word": source, "target_word": target}
                    for source, target in items
                ]
            )
        return file_vo({**values, "created_at": now, "updated_at": None})

    async def update(self, file_id: str, body: CorrectWordFileBody, user: AuthUser) -> None:
        self.validate(body, check_size=False)
        assert body.file_name is not None
        assert body.content is not None
        items = _parse_lines(body.content)
        async with self.repository.session.begin():
            row = await self.repository.get_file(file_id, for_update=True)
            if row is None:
                return
            if await self.repository.name_exists(user.id, body.file_name, file_id):
                raise AppError(500, f"文件名已存在：{body.file_name}")
            await self.repository.delete_items(file_id)
            await self.repository.insert_items(
                [
                    {"id": uuid.uuid4().hex, "file_id": file_id, "source_word": source, "target_word": target}
                    for source, target in items
                ]
            )
            await self.repository.update_file(
                {
                    "id": file_id,
                    "file_name": body.file_name,
                    "word_count": len(items),
                    "content": "\n".join(body.content),
                    "updater": user.id,
                    "now": shanghai_now_naive(),
                }
            )

    async def page(self, user: AuthUser, page: str | None, limit: str | None) -> dict[str, Any]:
        current, size = max(int(page or "1"), 1), int(limit or "10")
        rows, total = await self.repository.list_files(user.id, offset=(current - 1) * size, limit=size)
        return {"total": total, "list": [file_vo(row) for row in rows]}

    async def all(self, user: AuthUser) -> list[dict[str, Any]]:
        rows, _ = await self.repository.list_files(user.id)
        return [file_vo(row) for row in rows]

    async def get(self, file_id: str) -> dict[str, Any] | None:
        row = await self.repository.get_file(file_id)
        return file_vo(row) if row else None

    async def delete(self, file_ids: list[str]) -> None:
        async with self.repository.session.begin():
            for file_id in file_ids:
                if file_id and file_id.strip():
                    await self.repository.delete_file_graph(file_id.strip())
