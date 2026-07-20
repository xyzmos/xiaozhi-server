from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from typing import Any
from urllib.parse import quote_plus, urlsplit, urlunsplit

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from websockets.asyncio.client import connect


def _java_aes_key(value: str) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) in {16, 24, 32}:
        return raw
    return raw[:32].ljust(32, b"\x00")


def encrypt_agent_token(agent_id: str, key: str) -> str:
    digest = hashlib.md5(agent_id.encode("utf-8"), usedforsecurity=False).hexdigest()
    plain_text = f'{{"agentId": "{digest}"}}'.encode()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plain_text) + padder.finalize()
    # ECB is required for byte-for-byte compatibility with Java AES/ECB/PKCS5Padding.
    encryptor = Cipher(algorithms.AES(_java_aes_key(key)), modes.ECB()).encryptor()  # noqa: S305
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(encrypted).decode("ascii")


def build_agent_mcp_address(endpoint: str | None, agent_id: str) -> str | None:
    if endpoint is None or not endpoint.strip() or endpoint == "null":
        return None
    parsed = urlsplit(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("mcp的地址存在错误，请进入参数管理修改mcp接入点地址")
    marker = "key="
    marker_index = parsed.query.find(marker)
    # Java takes everything following the first key= marker, including subsequent query text.
    key = parsed.query[marker_index + len(marker) :] if marker_index >= 0 else parsed.query[3:]
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path
    parent = path[: path.rfind("/")] if "/" in path else ""
    base = urlunsplit((ws_scheme, parsed.netloc, parent, "", "")).rstrip("/")
    token = quote_plus(encrypt_agent_token(agent_id, key), safe="")
    return f"{base}/mcp/?token={token}"


INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {"roots": {"listChanged": False}, "sampling": {}},
        "clientInfo": {"name": "xz-mcp-broker", "version": "0.0.1"},
    },
    "id": 1,
}
INITIALIZED_NOTIFICATION = {"jsonrpc": "2.0", "method": "notifications/initialized"}
TOOLS_REQUEST = {"jsonrpc": "2.0", "method": "tools/list", "params": None, "id": 2}


async def _receive_matching(websocket: Any, request_id: int, timeout: float) -> dict[str, Any] | None:
    async def receive() -> dict[str, Any] | None:
        async for message in websocket:
            try:
                value = json.loads(message)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and value.get("id") == request_id:
                return value
        return None

    return await asyncio.wait_for(receive(), timeout=timeout)


async def list_mcp_tools(address: str, *, connect_timeout: float = 8.0, session_timeout: float = 10.0) -> list[str]:
    call_address = address.replace("/mcp/", "/call/")
    try:
        async with connect(
            call_address,
            open_timeout=connect_timeout,
            max_size=1024 * 1024,
            close_timeout=1,
        ) as websocket:
            await websocket.send(json.dumps(INITIALIZE_REQUEST, ensure_ascii=False, separators=(",", ":")))
            initialized = await _receive_matching(websocket, 1, session_timeout)
            if not initialized or "result" not in initialized or "error" in initialized:
                return []
            await websocket.send(json.dumps(INITIALIZED_NOTIFICATION, separators=(",", ":")))
            await websocket.send(json.dumps(TOOLS_REQUEST, separators=(",", ":")))
            response = await _receive_matching(websocket, 2, session_timeout)
            if not response or "error" in response:
                return []
            result = response.get("result")
            tools = result.get("tools") if isinstance(result, dict) else None
            if not isinstance(tools, list):
                return []
            return sorted(
                item["name"] for item in tools if isinstance(item, dict) and isinstance(item.get("name"), str)
            )
    # Java treats every connect/protocol/parse failure as an empty tool list.
    except Exception:
        return []
