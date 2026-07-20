from __future__ import annotations

from app.schemas.common import JavaModel


class TimbreBody(JavaModel):
    languages: str | None = None
    name: str | None = None
    remark: str | None = None
    reference_audio: str | None = None
    reference_text: str | None = None
    sort: int | None = 0
    tts_model_id: str | None = None
    tts_voice: str | None = None
    voice_demo: str | None = None
