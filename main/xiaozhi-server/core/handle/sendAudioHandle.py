"""音频发送处理器 - 事件驱动架构重构版"""

import json
import time
import asyncio
from typing import List, Optional, Union

from config.logger import setup_logging
from core.utils import textUtils
from core.utils.util import audio_to_data
from core.providers.tts.dto.dto import SentenceType
from core.infrastructure.di.container import DIContainer
from core.infrastructure.event.event_bus import EventBus
from core.infrastructure.websocket.transport import WebSocketTransport
from core.domain.events.audio_events import TTSAudioReadyEvent

TAG = __name__


class AudioSendHandler:
    """音频发送处理器 - 事件监听器模式"""

    def __init__(self, container: DIContainer, event_bus: EventBus):
        self.container = container
        self.event_bus = event_bus
        self.logger = setup_logging()

    async def handle_tts_audio_ready(self, event: TTSAudioReadyEvent):
        """处理TTS音频就绪事件"""
        try:
            session_id = event.session_id
            audio_data = event.audio_data
            text = event.text
            sentence_type_str = event.sentence_type

            # 将字符串转换为SentenceType枚举
            if sentence_type_str == SentenceType.FIRST.value:
                sentence_type = SentenceType.FIRST
            elif sentence_type_str == SentenceType.LAST.value:
                sentence_type = SentenceType.LAST
            else:
                sentence_type = SentenceType.MIDDLE

            self.logger.bind(tag=TAG).debug(f"收到音频事件: session={session_id}, type={sentence_type}, text={text}")

            await self.send_audio_message(session_id, sentence_type, audio_data, text)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"处理TTS音频事件失败: {e}", exc_info=True)

    async def send_audio_message(
        self,
        session_id: str,
        sentence_type: SentenceType,
        audios: Union[bytes, List[bytes]],
        text: Optional[str]
    ):
        """发送音频消息"""
        context = self.container.resolve('session_context', session_id=session_id)
        ws_transport = self.container.resolve('websocket_transport')

        # 获取TTS实例检查状态
        try:
            tts = self.container.resolve('tts', session_id=session_id)
        except Exception:
            tts = None

        if tts and hasattr(tts, 'tts_audio_first_sentence') and tts.tts_audio_first_sentence:
            self.logger.bind(tag=TAG).info(f"发送第一段语音: {text}")
            tts.tts_audio_first_sentence = False
            await self._send_tts_message(session_id, "start", None)

        if sentence_type == SentenceType.FIRST:
            await self._send_tts_message(session_id, "sentence_start", text)

        await self._send_audio(session_id, audios)

        if sentence_type is not SentenceType.MIDDLE:
            self.logger.bind(tag=TAG).info(f"发送音频消息: {sentence_type}, {text}")

        if sentence_type == SentenceType.LAST:
            await self._send_tts_message(session_id, "stop", None)
            context.client_is_speaking = False
            if context.close_after_chat:
                self.logger.info(f"会话 {session_id} 将在对话结束后关闭")
                await context.close()

    async def _send_audio(self, session_id: str, audios: Union[bytes, List[bytes]], frame_duration: int = 60):
        """发送音频数据"""
        if audios is None or len(audios) == 0:
            return

        context = self.container.resolve('session_context', session_id=session_id)
        ws_transport = self.container.resolve('websocket_transport')

        # 获取发送延迟配置
        send_delay = context.get_config("tts_audio_send_delay", -1) / 1000.0

        if isinstance(audios, bytes):
            await self._send_streaming_audio(session_id, audios, frame_duration, send_delay)
        else:
            await self._send_file_audio(session_id, audios, frame_duration, send_delay)

    async def _send_streaming_audio(self, session_id: str, audio: bytes, frame_duration: int, send_delay: float):
        """发送流式音频"""
        context = self.container.resolve('session_context', session_id=session_id)
        ws_transport = self.container.resolve('websocket_transport')

        # 重置流控状态
        if not hasattr(context, 'audio_flow_control') or context.audio_flow_control.get("sentence_id") != context.sentence_id:
            context.audio_flow_control = {
                "last_send_time": 0,
                "packet_count": 0,
                "start_time": time.perf_counter(),
                "sequence": 0,
                "sentence_id": context.sentence_id,
            }

        if context.client_abort:
            return

        context.last_activity_time = time.time() * 1000

        pre_buffer_count = 5
        flow_control = context.audio_flow_control
        current_time = time.perf_counter()

        if flow_control["packet_count"] < pre_buffer_count:
            pass
        elif send_delay > 0:
            await asyncio.sleep(send_delay)
        else:
            effective_packet = flow_control["packet_count"] - pre_buffer_count
            expected_time = flow_control["start_time"] + (effective_packet * frame_duration / 1000)
            delay = expected_time - current_time
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                flow_control["start_time"] += abs(delay)

        if context.conn_from_mqtt_gateway:
            timestamp, sequence = self._calculate_timestamp_and_sequence(
                flow_control["start_time"],
                flow_control["packet_count"],
                flow_control.get("sequence", 0),
                frame_duration
            )
            await self._send_to_mqtt_gateway(session_id, audio, timestamp, sequence)
        else:
            await ws_transport.send_binary(session_id, audio)

        context.client_is_speaking = True
        flow_control["packet_count"] += 1
        flow_control["sequence"] += 1
        flow_control["last_send_time"] = time.perf_counter()

    async def _send_file_audio(self, session_id: str, audios: List[bytes], frame_duration: int, send_delay: float):
        """发送文件音频"""
        context = self.container.resolve('session_context', session_id=session_id)
        ws_transport = self.container.resolve('websocket_transport')

        start_time = time.perf_counter()
        play_position = 0

        # 预缓冲
        pre_buffer_frames = min(5, len(audios))
        for i in range(pre_buffer_frames):
            if context.conn_from_mqtt_gateway:
                timestamp, sequence = self._calculate_timestamp_and_sequence(start_time, i, i, frame_duration)
                await self._send_to_mqtt_gateway(session_id, audios[i], timestamp, sequence)
            else:
                await ws_transport.send_binary(session_id, audios[i])
            context.client_is_speaking = True

        remaining_audios = audios[pre_buffer_frames:]

        for i, opus_packet in enumerate(remaining_audios):
            if context.client_abort:
                break

            context.last_activity_time = time.time() * 1000

            if send_delay > 0:
                await asyncio.sleep(send_delay)
            else:
                expected_time = start_time + (play_position / 1000)
                current_time = time.perf_counter()
                delay = expected_time - current_time
                if delay > 0:
                    await asyncio.sleep(delay)

            if context.conn_from_mqtt_gateway:
                packet_index = pre_buffer_frames + i
                timestamp, sequence = self._calculate_timestamp_and_sequence(start_time, packet_index, packet_index, frame_duration)
                await self._send_to_mqtt_gateway(session_id, opus_packet, timestamp, sequence)
            else:
                await ws_transport.send_binary(session_id, opus_packet)

            context.client_is_speaking = True
            play_position += frame_duration

    def _calculate_timestamp_and_sequence(self, start_time: float, packet_index: int, sequence: int, frame_duration: int):
        """计算时间戳和序列号"""
        timestamp = int((start_time + packet_index * frame_duration / 1000) * 1000) % (2**32)
        return timestamp, sequence

    async def _send_to_mqtt_gateway(self, session_id: str, opus_packet: bytes, timestamp: int, sequence: int):
        """发送到MQTT网关"""
        ws_transport = self.container.resolve('websocket_transport')

        header = bytearray(16)
        header[0] = 1
        header[2:4] = len(opus_packet).to_bytes(2, "big")
        header[4:8] = sequence.to_bytes(4, "big")
        header[8:12] = timestamp.to_bytes(4, "big")
        header[12:16] = len(opus_packet).to_bytes(4, "big")

        complete_packet = bytes(header) + opus_packet
        await ws_transport.send_binary(session_id, complete_packet)

    async def _send_tts_message(self, session_id: str, state: str, text: Optional[str]):
        """发送TTS状态消息"""
        if text is None and state == "sentence_start":
            return

        context = self.container.resolve('session_context', session_id=session_id)
        ws_transport = self.container.resolve('websocket_transport')

        message = {"type": "tts", "state": state, "session_id": session_id}
        if text is not None:
            message["text"] = textUtils.check_emoji(text)

        if state == "stop":
            tts_notify = context.get_config("enable_stop_tts_notify", False)
            if tts_notify:
                stop_tts_notify_voice = context.get_config("stop_tts_notify_voice", "config/assets/tts_notify.mp3")
                audios = audio_to_data(stop_tts_notify_voice, is_opus=True)
                await self._send_audio(session_id, audios)

            # 清除服务端讲话状态
            context.client_is_speaking = False

        await ws_transport.send_json(session_id, message)


def register_audio_send_handler(container: DIContainer, event_bus: EventBus):
    """注册音频发送处理器"""
    handler = AudioSendHandler(container, event_bus)

    # 订阅TTS音频就绪事件
    event_bus.subscribe(TTSAudioReadyEvent, handler.handle_tts_audio_ready)

    return handler
