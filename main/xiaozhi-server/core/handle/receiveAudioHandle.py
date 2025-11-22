import time
from config.logger import setup_logging
from core.infrastructure.event.event_types import (
    AudioDataReceivedEvent,
)
from core.infrastructure.di.container import DIContainer

TAG = __name__


# ==================== 新架构：事件驱动模式 ====================


class AudioMessageHandler:
    """音频消息处理器 - 使用事件监听器模式"""

    def __init__(self, container: DIContainer, event_bus):
        """初始化音频消息处理器

        Args:
            container: 依赖注入容器
            event_bus: 事件总线
        """
        self.container = container
        self.event_bus = event_bus
        self.logger = setup_logging()

        # 订阅音频数据接收事件
        self.event_bus.subscribe(
            AudioDataReceivedEvent, self.on_audio_received, is_async=True
        )
        self.logger.bind(tag=TAG).info("音频消息处理器已初始化")

    async def on_audio_received(self, event: AudioDataReceivedEvent):
        """处理音频数据接收事件

        Args:
            event: 音频数据接收事件
        """
        session_id = event.session_id
        audio_data = event.data

        try:
            # 从容器解析会话上下文
            context = self._get_session_context(session_id)
            if not context:
                self.logger.bind(tag=TAG).warning(f"会话 {session_id} 未找到")
                return

            # 调用原有的音频处理逻辑
            await handleAudioMessage(context, audio_data)

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"处理音频消息时出错: {e}", exc_info=True)

    def _get_session_context(self, session_id: str):
        """从容器获取会话上下文

        Args:
            session_id: 会话ID

        Returns:
            会话上下文对象
        """
        try:
            return self.container.resolve("session_context", session_id=session_id)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"获取会话上下文失败: {e}")
            return None


async def handleAudioMessage(context, audio):
    """处理音频消息

    Args:
        context: SessionContext 会话上下文
        audio: 音频数据
    """
    logger = setup_logging()
    try:
        # 使用 AudioProcessingService 处理音频
        audio_service = context.container.resolve("audio_service")

        # 创建音频数据事件并处理
        event = AudioDataReceivedEvent(
            session_id=context.session_id,
            data=audio,
            timestamp=time.time()
        )
        await audio_service.handle_audio_data(event)

    except Exception as e:
        logger.bind(tag=TAG).error(f"处理音频消息失败: {e}", exc_info=True)


def register_audio_receive_handler(container: DIContainer, event_bus):
    """注册音频接收处理器

    Args:
        container: 依赖注入容器
        event_bus: 事件总线

    Returns:
        AudioMessageHandler: 处理器实例
    """
    handler = AudioMessageHandler(container, event_bus)
    return handler
