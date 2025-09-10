from typing import Dict, Any

from core.handle.helloHandle import handleHelloMessage
from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from core.session.session_context import SessionContext


class HelloTextMessageHandler(TextMessageHandler):
    """Hello消息处理器"""

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.HELLO

    async def handle(self, conn, msg_json: Dict[str, Any], session_context: SessionContext) -> None:
        await handleHelloMessage(conn, msg_json, session_context)