from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx


class MqttGatewayError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def daily_authorization_tokens(signature_key: str, now: datetime | None = None) -> list[str]:
    if not signature_key.strip() or signature_key.strip().lower() == "null":
        raise MqttGatewayError("MQTT Gateway signature key is empty")
    instant = now or datetime.now(tz=timezone.utc)
    utc_date = instant.astimezone(timezone.utc).date()
    dates: tuple[date, date, date] = (utc_date, utc_date - timedelta(days=1), utc_date + timedelta(days=1))
    return [hashlib.sha256(f"{value.isoformat()}{signature_key}".encode()).hexdigest() for value in dates]


async def post_json(
    url: str,
    body: Any,
    signature_key: str,
    *,
    timeout_seconds: float,
    now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    owns_client = client is None
    selected = client or httpx.AsyncClient()
    last_unauthorized: int | None = None
    try:
        for token in daily_authorization_tokens(signature_key, now):
            response = await selected.post(
                url,
                content=encoded,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                timeout=timeout_seconds,
            )
            if response.status_code == 401:
                last_unauthorized = response.status_code
                continue
            if not 200 <= response.status_code < 300:
                raise MqttGatewayError(
                    f"MQTT Gateway request failed with HTTP status {response.status_code}",
                    response.status_code,
                )
            return response.text
    finally:
        if owns_client:
            await selected.aclose()
    raise MqttGatewayError(
        "MQTT Gateway rejected all daily authorization tokens"
        + ("" if last_unauthorized is None else f" (HTTP {last_unauthorized})"),
        last_unauthorized,
    )
