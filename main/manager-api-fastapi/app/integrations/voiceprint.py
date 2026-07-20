from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


class VoicePrintIntegrationError(RuntimeError):
    def __init__(self, code: int, message: str | None = None, params: tuple[object, ...] = ()):
        super().__init__(message or str(code))
        self.code = code
        self.message = message
        self.params = params


@dataclass(slots=True, frozen=True)
class VoicePrintEndpoint:
    base_url: str
    authorization: str

    @classmethod
    def parse(cls, configured_url: str | None) -> VoicePrintEndpoint:
        if configured_url is None:
            raise VoicePrintIntegrationError(10084)
        parsed = urlsplit(configured_url)
        if not parsed.scheme or not parsed.hostname:
            raise VoicePrintIntegrationError(10084)
        marker = "key="
        marker_index = parsed.query.find(marker)
        key = parsed.query[marker_index + len(marker) :] if marker_index >= 0 else parsed.query[3:]
        port = f":{parsed.port}" if parsed.port is not None else ""
        return cls(f"{parsed.scheme}://{parsed.hostname}{port}", f"Bearer {key}")


class VoicePrintClient:
    def __init__(self, configured_url: str, *, timeout: float = 10.0, client: httpx.AsyncClient | None = None):
        self.endpoint = VoicePrintEndpoint.parse(configured_url)
        self.timeout = timeout
        self._client = client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        data: Mapping[str, str] | None = None,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
    ) -> httpx.Response:
        headers = {"Authorization": self.endpoint.authorization}
        if self._client is not None:
            return await self._client.request(
                method, f"{self.endpoint.base_url}{path}", headers=headers, data=data, files=files
            )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.request(
                method, f"{self.endpoint.base_url}{path}", headers=headers, data=data, files=files
            )

    async def identify(self, speaker_ids: list[str], audio: bytes) -> tuple[str | None, float | None] | None:
        if not speaker_ids:
            return None
        response = await self._request(
            "POST",
            "/voiceprint/identify",
            data={"speaker_ids": ",".join(speaker_ids)},
            files={"file": ("VoicePrint.WAV", audio, "application/octet-stream")},
        )
        if response.status_code != 200:
            raise VoicePrintIntegrationError(10091)
        try:
            payload = response.json()
        except ValueError as exc:
            raise VoicePrintIntegrationError(10091) from exc
        if not isinstance(payload, dict):
            return None
        speaker_id = payload.get("speaker_id")
        score = payload.get("score")
        return (
            str(speaker_id) if speaker_id is not None else None,
            float(score) if isinstance(score, int | float) else None,
        )

    async def register(self, speaker_id: str, audio: bytes) -> None:
        response = await self._request(
            "POST",
            "/voiceprint/register",
            data={"speaker_id": speaker_id},
            files={"file": ("VoicePrint.WAV", audio, "application/octet-stream")},
        )
        if response.status_code != 200:
            raise VoicePrintIntegrationError(10087)
        if "true" not in response.text:
            raise VoicePrintIntegrationError(10088)

    async def cancel(self, speaker_id: str) -> None:
        response = await self._request("DELETE", f"/voiceprint/{speaker_id}")
        if response.status_code != 200:
            raise VoicePrintIntegrationError(10089)
        if "true" not in response.text:
            raise VoicePrintIntegrationError(10090)
