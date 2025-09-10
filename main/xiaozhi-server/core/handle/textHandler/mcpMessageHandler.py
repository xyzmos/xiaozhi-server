import asyncio
from typing import Dict, Any

from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from core.providers.tools.device_mcp import handle_mcp_message
from core.session.session_context import SessionContext


class McpTextMessageHandler(TextMessageHandler):
    """MCP消息处理器"""

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.MCP

    async def handle(self, conn, msg_json: Dict[str, Any], session_context: SessionContext) -> None:
        if "payload" in msg_json:
            asyncio.create_task(
                handle_mcp_message(conn, conn.mcp_client, msg_json["payload"])
            )