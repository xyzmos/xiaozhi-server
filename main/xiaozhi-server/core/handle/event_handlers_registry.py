"""事件处理器注册表 - 统一注册所有事件处理器"""

from config.logger import setup_logging
from core.infrastructure.di.container import DIContainer
from core.infrastructure.event.event_bus import EventBus

# 导入所有事件处理器
from core.handle.helloHandle import register_hello_handler
from core.handle.textHandle import register_text_handler
from core.handle.abortHandle import register_abort_handler
from core.handle.sendAudioHandle import register_audio_send_handler
from core.handle.receiveAudioHandle import register_audio_receive_handler
from core.handle.intentHandler import IntentMessageHandler
from core.handle.sessionLifecycleHandle import register_session_lifecycle_handler

TAG = __name__


def register_all_event_handlers(container: DIContainer, event_bus: EventBus):
    """注册所有事件处理器到事件总线

    Args:
        container: 依赖注入容器
        event_bus: 事件总线

    Returns:
        Dict: 所有注册的处理器实例
    """
    logger = setup_logging()
    logger.info("开始注册事件处理器...")

    handlers = {}

    try:
        # 注册会话生命周期处理器（必须最先注册）
        handlers['session_lifecycle'] = register_session_lifecycle_handler(container, event_bus)
        logger.debug("✓ 会话生命周期处理器已注册")

        # 注册 Hello 消息处理器
        handlers['hello'] = register_hello_handler(container, event_bus)
        logger.debug("✓ Hello 消息处理器已注册")

        # 注册文本消息处理器
        handlers['text'] = register_text_handler(container, event_bus)
        logger.debug("✓ 文本消息处理器已注册")

        # 注册中止消息处理器
        handlers['abort'] = register_abort_handler(container, event_bus)
        logger.debug("✓ 中止消息处理器已注册")

        # 注册音频发送处理器
        handlers['audio_send'] = register_audio_send_handler(container, event_bus)
        logger.debug("✓ 音频发送处理器已注册")

        # 注册音频接收处理器
        handlers['audio_receive'] = register_audio_receive_handler(container, event_bus)
        logger.debug("✓ 音频接收处理器已注册")

        # 注册意图消息处理器
        handlers['intent'] = IntentMessageHandler(container)
        logger.debug("✓ 意图消息处理器已注册")

        logger.info(f"事件处理器注册完成，共注册 {len(handlers)} 个处理器")

    except Exception as e:
        logger.error(f"注册事件处理器失败: {e}", exc_info=True)
        raise

    return handlers


def unregister_all_event_handlers(event_bus: EventBus):
    """注销所有事件处理器

    Args:
        event_bus: 事件总线
    """
    logger = setup_logging()
    logger.info("注销所有事件处理器...")
    event_bus.clear()
    logger.info("事件处理器已清空")
