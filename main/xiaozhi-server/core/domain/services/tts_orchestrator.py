"""TTS 编排服务 - 替代直接操作 conn.tts"""

import time
import uuid
from typing import TYPE_CHECKING, Optional

from config.logger import setup_logging
from core.providers.tts.dto.dto import ContentType, SentenceType, TTSMessageDTO
from core.infrastructure.event.event_types import TTSRequestEvent, TTSAudioReadyEvent

if TYPE_CHECKING:
    from core.infrastructure.di.container import DIContainer
    from core.infrastructure.event.event_bus import EventBus


class TTSOrchestrator:
    """TTS 编排服务 - 替代直接操作 conn.tts"""

    def __init__(self, container: 'DIContainer', event_bus: 'EventBus'):
        self.container = container
        self.event_bus = event_bus
        self.logger = setup_logging()

    async def add_message(
        self,
        session_id: str,
        sentence_type: SentenceType,
        content_type: ContentType,
        content_detail: Optional[str] = None,
        content_file: Optional[str] = None
    ):
        """添加 TTS 消息（替代 conn.tts.tts_text_queue.put）"""
        context = self.container.resolve('session_context', session_id=session_id)
        if not context:
            self.logger.error(f"会话 {session_id} 的上下文不存在")
            return

        tts = self.container.resolve('tts', session_id=session_id)
        if not tts:
            self.logger.error(f"TTS 服务不可用: session={session_id}")
            return

        # 创建 TTS 消息
        message = TTSMessageDTO(
            sentence_id=context.sentence_id,
            sentence_type=sentence_type,
            content_type=content_type,
            content_detail=content_detail,
            content_file=content_file
        )

        # 放入 TTS 队列
        tts.tts_text_queue.put(message)
        self.logger.debug(f"已添加 TTS 消息: type={sentence_type}, content={content_detail[:20] if content_detail else None}")

    async def add_first_message(self, session_id: str):
        """添加首句标记"""
        await self.add_message(
            session_id=session_id,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION
        )

    async def add_last_message(self, session_id: str):
        """添加末句标记"""
        await self.add_message(
            session_id=session_id,
            sentence_type=SentenceType.LAST,
            content_type=ContentType.ACTION
        )

    async def add_text_message(self, session_id: str, text: str):
        """添加文本消息"""
        await self.add_message(
            session_id=session_id,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.TEXT,
            content_detail=text
        )

    async def synthesize_one_sentence(self, session_id: str, text: str):
        """合成单句（简化接口）"""
        context = self.container.resolve('session_context', session_id=session_id)
        if not context:
            self.logger.error(f"会话 {session_id} 的上下文不存在")
            return

        # 如果没有 sentence_id，生成一个
        if not context.sentence_id:
            context.sentence_id = str(uuid.uuid4().hex)

        # 获取 TTS 服务
        tts = self.container.resolve('tts', session_id=session_id)
        if not tts:
            self.logger.error(f"TTS 服务不可用: session={session_id}")
            return

        # 发送首句标记
        await self.add_first_message(session_id)

        # 使用 TTS 服务的方法
        tts.tts_one_sentence(ContentType.TEXT, content_detail=text)

        # 发送末句标记
        await self.add_last_message(session_id)

    async def play_audio_file(self, session_id: str, file_path: str):
        """播放音频文件"""
        await self.add_message(
            session_id=session_id,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.FILE,
            content_file=file_path
        )

    async def play_audio_with_text(
        self,
        session_id: str,
        file_path: str,
        text: str,
        sentence_type: SentenceType = SentenceType.MIDDLE
    ):
        """播放音频文件并显示文本"""
        from core.utils.util import audio_to_data

        context = self.container.resolve('session_context', session_id=session_id)
        if not context:
            self.logger.error(f"会话 {session_id} 的上下文不存在")
            return

        tts = self.container.resolve('tts', session_id=session_id)
        if not tts:
            self.logger.error(f"TTS 服务不可用: session={session_id}")
            return

        opus_packets = audio_to_data(file_path)
        tts.tts_audio_queue.put((sentence_type, opus_packets, text))

    async def cleanup(self, session_id: str):
        """清理资源"""
        tts = self.container.resolve('tts', session_id=session_id)
        if tts:
            # 清空队列
            while not tts.tts_text_queue.empty():
                try:
                    tts.tts_text_queue.get_nowait()
                except:
                    break

            while not tts.tts_audio_queue.empty():
                try:
                    tts.tts_audio_queue.get_nowait()
                except:
                    break

        self.logger.debug(f"已清理 TTS 资源: session={session_id}")

    async def abort(self, session_id: str):
        """中止当前 TTS 播放"""
        context = self.container.resolve('session_context', session_id=session_id)
        if context:
            context.client_abort = True

        await self.cleanup(session_id)

    async def handle_tts_request(self, event: TTSRequestEvent):
        """处理 TTS 请求事件"""
        session_id = event.session_id
        text = event.text

        if text:
            await self.add_text_message(session_id, text)


def register_tts_orchestrator(container: 'DIContainer', event_bus: 'EventBus'):
    """注册 TTS 编排服务"""
    service = TTSOrchestrator(container, event_bus)
    event_bus.subscribe(TTSRequestEvent, service.handle_tts_request)
    return service
