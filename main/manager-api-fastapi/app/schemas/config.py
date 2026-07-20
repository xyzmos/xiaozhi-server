from __future__ import annotations

from pydantic import field_validator

from app.schemas.common import JavaModel


def _not_blank(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("must not be blank")
    return value


class AgentModelsRequest(JavaModel):
    mac_address: str
    client_id: str
    selected_module: dict[str, str]

    _validate_required = field_validator("mac_address", "client_id")(_not_blank)


class CorrectWordsRequest(JavaModel):
    mac_address: str

    _validate_required = field_validator("mac_address")(_not_blank)
