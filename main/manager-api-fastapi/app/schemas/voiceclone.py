from __future__ import annotations

from app.schemas.common import JavaModel


class VoiceResourceCreateRequest(JavaModel):
    model_id: str | None = None
    voice_ids: list[str] | None = None
    user_id: int | None = None
    languages: str | None = None


class VoiceCloneRenameRequest(JavaModel):
    id: str | None = None
    name: str | None = None


class VoiceCloneTrainRequest(JavaModel):
    clone_id: str | None = None
