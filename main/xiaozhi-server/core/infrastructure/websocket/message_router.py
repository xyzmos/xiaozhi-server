"""WebSocket 消息路由器 - 将消息转换为事件"""

import time
from typing import Union

from core.infrastructure.di import DIContainer
from core.infrastructure.event import (
    AudioDataReceivedEvent,
    EventBus,
    TextMessageReceivedEvent,
)
from config.logger import setup_logging


class WebSocketMessageRouter:
    """WebSocket 消息路由器 - 负责路由消息到事件总线"""

    def __init__(self, event_bus: EventBus, container: DIContainer):
        self.event_bus = event_bus
        self.container = container
        self.logger = setup_logging()

    async def route_message(self, session_id: str, message: Union[str, bytes]):
        """路由消息到事件总线

        Args:
            session_id: 会话ID
            message: 收到的消息（文本或二进制）
        """
        try:
            # 获取会话上下文
            context = self.container.resolve('session_context', session_id=session_id)

            if isinstance(message, str):
                # 文本消息 - 更新活动时间
                context.update_activity_time()
                await self._route_text_message(session_id, message)
            elif isinstance(message, bytes):
                # 音频消息 - 不在这里更新活动时间，由VAD检测到声音时才更新
                await self._route_audio_message(session_id, message, context)
            else:
                self.logger.warning(f"未知的消息类型: {type(message)}")

        except Exception as e:
            self.logger.error(f"路由消息失败 {session_id}: {e}", exc_info=True)

    async def _route_text_message(self, session_id: str, text: str):
        """路由文本消息

        Args:
            session_id: 会话ID
            text: 文本内容
        """
        self.logger.debug(f"收到文本消息 {session_id}: {text[:100]}")

        await self.event_bus.publish(TextMessageReceivedEvent(
            session_id=session_id,
            content=text,
            timestamp=time.time()
        ))

    async def _route_audio_message(self, session_id: str, data: bytes, context):
        """路由音频消息

        Args:
            session_id: 会话ID
            data: 音频数据
            context: 会话上下文
        """
        # 检查是否来自 MQTT 网关
        if context.conn_from_mqtt_gateway and len(data) >= 16:
            # 解析 MQTT 头部
            # 格式: [8字节保留] [4字节时间戳] [4字节音频长度] [音频数据]
            timestamp = int.from_bytes(data[8:12], "big")
            audio_length = int.from_bytes(data[12:16], "big")

            if audio_length > 0 and len(data) >= 16 + audio_length:
                audio_data = data[16:16 + audio_length]
            else:
                audio_data = data[16:]

            self.logger.debug(f"收到 MQTT 音频消息 {session_id}: {len(audio_data)} 字节, 时间戳: {timestamp}")

            # 发布带时间戳的音频事件
            await self.event_bus.publish(AudioDataReceivedEvent(
                session_id=session_id,
                data=audio_data,
                timestamp=timestamp
            ))
        else:
            # 普通音频数据
            self.logger.debug(f"收到普通音频消息 {session_id}: {len(data)} 字节")

            await self.event_bus.publish(AudioDataReceivedEvent(
                session_id=session_id,
                data=data,
                timestamp=time.time()
            ))
