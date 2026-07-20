from __future__ import annotations

from app.schemas.common import JavaModel


class CorrectWordFileBody(JavaModel):
    file_name: str | None = None
    content: list[str] | None = None
    file_size: int | None = None
