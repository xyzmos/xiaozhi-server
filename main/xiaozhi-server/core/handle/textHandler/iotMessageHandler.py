import asyncio
from typing import Dict, Any

from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from core.providers.tools.device_iot import handleIotStatus, handleIotDescriptors
from core.session.session_context import SessionContext


class IotTextMessageHandler(TextMessageHandler):
    """IOT消息处理器"""

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.IOT

    async def handle(self, conn, msg_json: Dict[str, Any], session_context: SessionContext) -> None:
        if "descriptors" in msg_json:
            asyncio.create_task(handleIotDescriptors(conn, msg_json["descriptors"]))
        if "states" in msg_json:
            asyncio.create_task(handleIotStatus(conn, msg_json["states"]))