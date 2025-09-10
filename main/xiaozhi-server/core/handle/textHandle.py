from core.handle.textMessageHandlerRegistry import TextMessageHandlerRegistry
from core.handle.textMessageProcessor import TextMessageProcessor
from core.session.session_context import SessionContext

TAG = __name__

# 全局处理器注册表
message_registry = TextMessageHandlerRegistry()

# 创建全局消息处理器实例
message_processor = TextMessageProcessor(message_registry)

async def handleTextMessage(conn, message, session_context: SessionContext):
    """处理文本消息"""
    await message_processor.process_message(conn, message, session_context)
