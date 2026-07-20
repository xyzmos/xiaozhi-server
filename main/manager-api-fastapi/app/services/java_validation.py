from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.core.i18n import LANGUAGE_FILES, _load_properties, resolve_language


@lru_cache(maxsize=16)
def _validation_messages(language: str, directory: str) -> dict[str, str]:
    root = Path(directory)
    values = _load_properties(root / "validation.properties")
    localized = LANGUAGE_FILES[language].replace("messages_", "validation_")
    values.update(_load_properties(root / localized))
    return values


def validation_message(key: str, accept_language: str | None) -> str:
    language = resolve_language(accept_language)
    return _validation_messages(language, str(get_settings().i18n_dir)).get(key, key)
