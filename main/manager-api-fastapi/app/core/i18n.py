from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

LANGUAGE_FILES: dict[str, str] = {
    "zh-CN": "messages_zh_CN.properties",
    "zh-TW": "messages_zh_TW.properties",
    "en-US": "messages_en_US.properties",
    "de-DE": "messages_de_DE.properties",
    "vi-VN": "messages_vi_VN.properties",
    "pt-BR": "messages_pt_BR.properties",
}
_UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


def resolve_language(accept_language: str | None) -> str:
    if not accept_language:
        return "zh-CN"
    primary = accept_language.split(",", 1)[0].split(";", 1)[0].strip().replace("_", "-")
    exact = {key.lower(): key for key in LANGUAGE_FILES}
    if primary.lower() in exact:
        return exact[primary.lower()]
    prefix = primary.lower().split("-", 1)[0]
    return {
        "zh": "zh-CN",
        "en": "en-US",
        "de": "de-DE",
        "vi": "vi-VN",
        "pt": "pt-BR",
    }.get(prefix, "zh-CN")


def _unescape(value: str) -> str:
    decoded = _UNICODE_ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), value)
    return (
        decoded.replace("\\t", "\t")
        .replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\f", "\f")
        .replace("\\=", "=")
        .replace("\\:", ":")
        .replace("\\ ", " ")
        .replace("\\\\", "\\")
    )


def _load_properties(path: Path) -> dict[str, str]:
    messages: dict[str, str] = {}
    if not path.exists():
        return messages
    continuation = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = continuation + raw_line
        if line.endswith("\\") and not line.endswith("\\\\"):
            continuation = line[:-1]
            continue
        continuation = ""
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")):
            continue
        delimiter = "=" if "=" in line else ":"
        if delimiter not in line:
            continue
        key, value = line.split(delimiter, 1)
        messages[key.strip()] = _unescape(value.strip())
    return messages


@lru_cache(maxsize=16)
def messages_for(language: str, i18n_dir: str | None = None) -> dict[str, str]:
    directory = Path(i18n_dir) if i18n_dir else get_settings().i18n_dir
    default_messages = _load_properties(directory / "messages.properties")
    default_messages.update(_load_properties(directory / LANGUAGE_FILES.get(language, LANGUAGE_FILES["zh-CN"])))
    return default_messages


def message_for(code: int, accept_language: str | None, *params: object) -> str:
    language = resolve_language(accept_language)
    template = messages_for(language).get(str(code), str(code))
    for index, param in enumerate(params):
        template = template.replace("{" + str(index) + "}", str(param))
    return template


def clear_i18n_cache() -> None:
    messages_for.cache_clear()
