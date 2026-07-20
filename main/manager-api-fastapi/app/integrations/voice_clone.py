from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class VoiceCloneProviderError(Exception):
    code: int
    message: str

    def __str__(self) -> str:
        return self.message


class VoiceCloneIntegration:
    ENDPOINT = "https://openspeech.bytedance.com/api/v1/mega_tts/audio/upload"

    def __init__(
        self,
        *,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
        endpoint: str | None = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.client = client
        self.endpoint = endpoint or self.ENDPOINT

    async def train_huoshan(
        self,
        *,
        appid: str,
        access_token: str,
        voice: bytes,
        speaker_id: str,
    ) -> str:
        request_body: dict[str, Any] = {
            "appid": appid,
            "audios": [
                {
                    "audio_bytes": base64.b64encode(voice).decode("ascii"),
                    "audio_format": "wav",
                }
            ],
            "source": 2,
            "language": 0,
            "model_type": 1,
            "speaker_id": speaker_id,
        }
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient()
        try:
            response = await client.post(
                self.endpoint,
                content=json.dumps(request_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer;{access_token}",
                    "Resource-Id": "seed-icl-1.0",
                },
                timeout=self.timeout_seconds,
            )
            try:
                payload = response.json()
            except (json.JSONDecodeError, ValueError) as exc:
                raise VoiceCloneProviderError(10157, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise VoiceCloneProviderError(10157, str(exc)) from exc
        finally:
            if owns_client:
                await client.aclose()

        if not isinstance(payload, dict):
            raise VoiceCloneProviderError(10156, "响应格式错误，缺少BaseResp字段")
        base_response = payload.get("BaseResp")
        if isinstance(base_response, dict):
            raw_status = base_response.get("StatusCode")
            try:
                status_code = int(raw_status) if raw_status is not None else None
            except (TypeError, ValueError):
                status_code = None
            returned_speaker = payload.get("speaker_id")
            if status_code == 0 and isinstance(returned_speaker, str) and returned_speaker.strip():
                return returned_speaker
            status_message = base_response.get("StatusMessage")
            message = str(status_message) if status_message not in (None, "") else "训练失败"
            raise VoiceCloneProviderError(500, message)
        payload_message = payload.get("message")
        if payload_message not in (None, ""):
            raise VoiceCloneProviderError(500, str(payload_message))
        raise VoiceCloneProviderError(10156, "响应格式错误，缺少BaseResp字段")
