"""中止消息处理器 - 事件驱动架构重构版"""

from config.logger import setup_logging
from core.infrastructure.event.event_types import ClientAbortEvent
from core.infrastructure.di.container import DIContainer
from core.infrastructure.event.event_bus import EventBus

TAG = __name__


class AbortMessageHandler:
    """中止消息处理器 - 完全事件驱动"""

    def __init__(self, container: DIContainer, event_bus: EventBus):
        self.container = container
        self.event_bus = event_bus
        self.logger = setup_logging()

    async def handle(self, event: ClientAbortEvent):
        """处理中止事件 - 完全通过事件和服务"""
        session_id = event.session_id

        self.logger.bind(tag=TAG).info(f"收到中止请求: {session_id}")

        # 获取会话上下文
        context = self.container.resolve('session_context', session_id=session_id)
        ws_transport = self.container.resolve('websocket_transport')

        # 设置中止标志
        context.client_abort = True

        # 清理TTS队列 - 通过TTS服务
        try:
            tts_orchestrator = self.container.resolve('tts_orchestrator', session_id=session_id)
            await tts_orchestrator.clear_queue()
        except Exception as e:
            self.logger.error(f"清理TTS队列失败: {e}")

        # 清理ASR队列 - 通过ASR服务
        try:
            asr_service = self.container.resolve('asr_service', session_id=session_id)
            await asr_service.clear_buffer()
        except Exception as e:
            self.logger.error(f"清理ASR缓冲失败: {e}")

        # 清除客户端说话状态
        context.client_is_speaking = False
        context.llm_finish_task = True

        # 通知客户端停止TTS
        await ws_transport.send_json(session_id, {
            "type": "tts",
            "state": "stop",
            "session_id": session_id
        })

        self.logger.bind(tag=TAG).info(f"中止请求处理完成: {session_id}")


def register_abort_handler(container: DIContainer, event_bus: EventBus):
    """注册中止消息处理器到事件总线"""
    handler = AbortMessageHandler(container, event_bus)
    event_bus.subscribe(ClientAbortEvent, handler.handle)
    return handler
