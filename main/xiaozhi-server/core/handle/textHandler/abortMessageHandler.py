from typing import Dict, Any

from core.handle.abortHandle import handleAbortMessage
from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from core.session.session_context import SessionContext


class AbortTextMessageHandler(TextMessageHandler):
    """Abort消息处理器"""

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.ABORT

    async def handle(self, conn, msg_json: Dict[str, Any], session_context: SessionContext) -> None:
        await handleAbortMessage(conn)
