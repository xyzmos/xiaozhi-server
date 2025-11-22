"""音频处理服务 - 整合 VAD + ASR 逻辑"""

import time
import json
import asyncio
from typing import TYPE_CHECKING

from config.logger import setup_logging
from core.infrastructure.event.event_types import (
    AudioDataReceivedEvent,
    ClientAbortEvent,
    VADSpeechStartEvent,
    VADSpeechEndEvent,
    ASRTranscriptEvent,
)

if TYPE_CHECKING:
    from core.infrastructure.di.container import DIContainer
    from core.infrastructure.event.event_bus import EventBus
    from core.application.context import SessionContext


class AudioProcessingService:
    """音频处理服务 - 整合 VAD + ASR"""

    def __init__(self, container: 'DIContainer', event_bus: 'EventBus'):
        self.container = container
        self.event_bus = event_bus
        self.logger = setup_logging()

    async def handle_audio_data(self, event: AudioDataReceivedEvent):
        """处理音频数据事件"""
        session_id = event.session_id
        audio_data = event.data

        # 获取会话上下文
        context: 'SessionContext' = self.container.resolve('session_context', session_id=session_id)
        if not context:
            self.logger.error(f"会话 {session_id} 的上下文不存在")
            return

        # 获取 VAD 和 ASR 服务
        vad = self.container.resolve('vad')
        asr = self.container.resolve('asr', session_id=session_id)

        if not vad or not asr:
            self.logger.error(f"VAD 或 ASR 服务不可用: session={session_id}")
            return

        # VAD 检测
        have_voice = vad.is_vad(context, audio_data)

        # 如果设备刚刚被唤醒，短暂忽略 VAD 检测
        if context.just_woken_up:
            have_voice = False
            asr.asr_audio.clear()
            if not hasattr(context, 'vad_resume_task') or context.vad_resume_task.done():
                context.vad_resume_task = asyncio.create_task(
                    self._resume_vad_detection(context)
                )
            return

        # manual 模式下不打断正在播放的内容
        if have_voice:
            if context.client_is_speaking and context.client_listen_mode != "manual":
                await self.event_bus.publish(ClientAbortEvent(
                    session_id=session_id,
                    timestamp=time.time(),
                    reason="user_interrupt"
                ))

        # 设备长时间空闲检测
        await self._no_voice_close_connect(context, have_voice)

        # 传递给 ASR 服务
        await asr.receive_audio(audio_data, have_voice)

    async def _resume_vad_detection(self, context: 'SessionContext'):
        """恢复 VAD 检测"""
        await asyncio.sleep(2)
        context.just_woken_up = False

    async def _no_voice_close_connect(self, context: 'SessionContext', have_voice: bool):
        """设备长时间空闲检测，用于 say goodbye"""
        # 注意: last_activity_time 由 VAD 负责更新，这里只检查超时

        # 只有在已经初始化过时间戳的情况下才进行超时检查
        if context.last_activity_time > 0.0:
            no_voice_time = time.time() * 1000 - context.last_activity_time
            close_connection_no_voice_time = int(
                context.get_config("close_connection_no_voice_time", 120)
            )

            if (
                not context.close_after_chat
                and no_voice_time > 1000 * close_connection_no_voice_time
            ):
                context.close_after_chat = True
                context.client_abort = False

                end_prompt = context.get_config("end_prompt", {})
                if end_prompt and end_prompt.get("enable", True) is False:
                    self.logger.info(f"会话 {context.session_id} 结束对话，无需发送结束提示语")
                    # 发布会话关闭事件
                    from core.infrastructure.event.event_types import SessionDestroyingEvent
                    await self.event_bus.publish(SessionDestroyingEvent(
                        session_id=context.session_id,
                        timestamp=time.time()
                    ))
                    return

                prompt = end_prompt.get("prompt")
                if not prompt:
                    prompt = "请你以```时间过得真快```未来头，用富有感情、依依不舍的话来结束这场对话吧。！"

                # 发布开始对话事件
                await self._start_to_chat(context, prompt)

    async def _start_to_chat(self, context: 'SessionContext', text: str):
        """开始对话"""
        from core.domain.services.intent_service import IntentService

        # 获取意图服务
        intent_service: IntentService = self.container.resolve('intent_service')

        # 发送 ASR 转录事件
        await self.event_bus.publish(ASRTranscriptEvent(
            session_id=context.session_id,
            timestamp=time.time(),
            text=text,
            is_final=True
        ))


def register_audio_service(container: 'DIContainer', event_bus: 'EventBus'):
    """注册音频处理服务到事件总线"""
    service = AudioProcessingService(container, event_bus)
    event_bus.subscribe(AudioDataReceivedEvent, service.handle_audio_data)
    return service
