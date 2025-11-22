import os
import io
import wave
import uuid
import json
import time
import queue
import asyncio
import traceback
import threading
import opuslib_next
import concurrent.futures
from abc import ABC, abstractmethod
from config.logger import setup_logging
from typing import Optional, Tuple, List, TYPE_CHECKING

if TYPE_CHECKING:
    from core.application.context import SessionContext
    from core.infrastructure.di.container import DIContainer
    from core.infrastructure.event.event_bus import EventBus

TAG = __name__
logger = setup_logging()


class ASRProviderBase(ABC):
    def __init__(self, config=None, session_context: Optional['SessionContext'] = None):
        self.config = config or {}
        self.context = session_context
        self.output_dir = self.config.get("output_dir", "tmp/")
        self.asr_audio_queue = queue.Queue()
        self.asr_priority_thread = None

    # 打开音频通道
    async def open_audio_channels(self, context: 'SessionContext', container: 'DIContainer', event_bus: 'EventBus'):
        """打开音频通道 - 接收 context 而非 conn"""
        self.context = context
        self.container = container
        self.event_bus = event_bus

        # 启动ASR处理线程
        self.asr_priority_thread = threading.Thread(
            target=self.asr_text_priority_thread, daemon=True
        )
        self.asr_priority_thread.start()

    # 有序处理ASR音频
    def asr_text_priority_thread(self):
        """ASR文本处理线程 - 不再接收conn参数"""
        while not self.context.lifecycle.is_stopped():
            try:
                message = self.asr_audio_queue.get(timeout=1)

                # 发布文本识别事件
                from core.infrastructure.event.event_types import TextRecognizedEvent
                future = asyncio.run_coroutine_threadsafe(
                    self.event_bus.publish(TextRecognizedEvent(
                        session_id=self.context.session_id,
                        timestamp=time.time(),
                        text=message,
                        is_final=True
                    )),
                    self.context.lifecycle.loop,
                )
                future.result()
            except queue.Empty:
                continue
            except Exception as e:
                logger.bind(tag=TAG).error(
                    f"处理ASR文本失败: {str(e)}, 类型: {type(e).__name__}, 堆栈: {traceback.format_exc()}"
                )
                continue

    # 接收音频
    async def receive_audio(self, audio: bytes, audio_have_voice: bool):
        """接收音频 - 使用context而非conn"""
        if self.context.client_listen_mode == "auto" or self.context.client_listen_mode == "realtime":
            have_voice = audio_have_voice
        else:
            have_voice = self.context.client_have_voice

        # 使用context的asr_audio属性
        if not hasattr(self.context, 'asr_audio'):
            self.context.asr_audio = []

        self.context.asr_audio.append(audio)
        if not have_voice and not self.context.client_have_voice:
            self.context.asr_audio = self.context.asr_audio[-10:]
            return

        if self.context.client_voice_stop:
            asr_audio_task = self.context.asr_audio.copy()
            self.context.asr_audio.clear()

            # 重置VAD状态
            self.context.client_have_voice = False
            self.context.client_voice_stop = False
            self.context.last_is_voice = False

            if len(asr_audio_task) > 15:
                await self.handle_voice_stop(asr_audio_task)

    # 处理语音停止
    async def handle_voice_stop(self, asr_audio_task: List[bytes]):
        """并行处理ASR和声纹识别 - 使用context而非conn"""
        try:
            from core.utils.util import remove_punctuation_and_length

            total_start_time = time.monotonic()

            # 准备音频数据
            if self.context.audio_format == "pcm":
                pcm_data = asr_audio_task
            else:
                pcm_data = self.decode_opus(asr_audio_task)

            combined_pcm_data = b"".join(pcm_data)

            # 预先准备WAV数据
            wav_data = None
            voiceprint_provider = self.container.resolve('voiceprint_provider', session_id=self.context.session_id) if hasattr(self, 'container') else None
            if voiceprint_provider and combined_pcm_data:
                wav_data = self._pcm_to_wav(combined_pcm_data)

            # 定义ASR任务
            def run_asr():
                start_time = time.monotonic()
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        result = loop.run_until_complete(
                            self.speech_to_text(asr_audio_task, self.context.session_id, self.context.audio_format)
                        )
                        end_time = time.monotonic()
                        logger.bind(tag=TAG).debug(f"ASR耗时: {end_time - start_time:.3f}s")
                        return result
                    finally:
                        loop.close()
                except Exception as e:
                    end_time = time.monotonic()
                    logger.bind(tag=TAG).error(f"ASR失败: {e}")
                    return ("", None)

            # 定义声纹识别任务
            def run_voiceprint():
                if not wav_data or not voiceprint_provider:
                    return None
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        result = loop.run_until_complete(
                            voiceprint_provider.identify_speaker(wav_data, self.context.session_id)
                        )
                        return result
                    finally:
                        loop.close()
                except Exception as e:
                    logger.bind(tag=TAG).error(f"声纹识别失败: {e}")
                    return None

            # 使用线程池执行器并行运行
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as thread_executor:
                asr_future = thread_executor.submit(run_asr)

                if voiceprint_provider and wav_data:
                    voiceprint_future = thread_executor.submit(run_voiceprint)

                    # 等待两个线程都完成
                    asr_result = asr_future.result(timeout=15)
                    voiceprint_result = voiceprint_future.result(timeout=15)

                    results = {"asr": asr_result, "voiceprint": voiceprint_result}
                else:
                    asr_result = asr_future.result(timeout=15)
                    results = {"asr": asr_result, "voiceprint": None}


            # 处理结果
            raw_text, _ = results.get("asr", ("", None))
            speaker_name = results.get("voiceprint", None)

            # 记录识别结果
            if raw_text:
                logger.bind(tag=TAG).info(f"识别文本: {raw_text}")
            if speaker_name:
                logger.bind(tag=TAG).info(f"识别说话人: {speaker_name}")

            # 性能监控
            total_time = time.monotonic() - total_start_time
            logger.bind(tag=TAG).debug(f"总处理耗时: {total_time:.3f}s")

            # 检查文本长度
            text_len, _ = remove_punctuation_and_length(raw_text)
            self.stop_ws_connection()

            if text_len > 0:
                # 构建包含说话人信息的JSON字符串
                enhanced_text = self._build_enhanced_text(raw_text, speaker_name)

                # 发布文本识别事件
                from core.infrastructure.event.event_types import TextRecognizedEvent
                await self.event_bus.publish(TextRecognizedEvent(
                    session_id=self.context.session_id,
                    timestamp=time.time(),
                    text=enhanced_text,
                    is_final=True
                ))

                # 上报ASR数据
                from core.handle.reportHandle import enqueue_asr_report
                enqueue_asr_report(self.context, enhanced_text, asr_audio_task)

        except Exception as e:
            logger.bind(tag=TAG).error(f"处理语音停止失败: {e}")
            import traceback
            logger.bind(tag=TAG).debug(f"异常详情: {traceback.format_exc()}")

    def _build_enhanced_text(self, text: str, speaker_name: Optional[str]) -> str:
        """构建包含说话人信息的文本"""
        if speaker_name and speaker_name.strip():
            return json.dumps({
                "speaker": speaker_name,
                "content": text
            }, ensure_ascii=False)
        else:
            return text

    def _pcm_to_wav(self, pcm_data: bytes) -> bytes:
        """将PCM数据转换为WAV格式"""
        if len(pcm_data) == 0:
            logger.bind(tag=TAG).warning("PCM数据为空，无法转换WAV")
            return b""
        
        # 确保数据长度是偶数（16位音频）
        if len(pcm_data) % 2 != 0:
            pcm_data = pcm_data[:-1]
        
        # 创建WAV文件头
        wav_buffer = io.BytesIO()
        try:
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(1)      # 单声道
                wav_file.setsampwidth(2)      # 16位
                wav_file.setframerate(16000)  # 16kHz采样率
                wav_file.writeframes(pcm_data)
            
            wav_buffer.seek(0)
            wav_data = wav_buffer.read()
            
            return wav_data
        except Exception as e:
            logger.bind(tag=TAG).error(f"WAV转换失败: {e}")
            return b""

    def stop_ws_connection(self):
        pass

    def save_audio_to_file(self, pcm_data: List[bytes], session_id: str) -> str:
        """PCM数据保存为WAV文件"""
        module_name = __name__.split(".")[-1]
        file_name = f"asr_{module_name}_{session_id}_{uuid.uuid4()}.wav"
        file_path = os.path.join(self.output_dir, file_name)

        with wave.open(file_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 2 bytes = 16-bit
            wf.setframerate(16000)
            wf.writeframes(b"".join(pcm_data))

        return file_path

    @abstractmethod
    async def speech_to_text(
        self, opus_data: List[bytes], session_id: str, audio_format="opus"
    ) -> Tuple[Optional[str], Optional[str]]:
        """将语音数据转换为文本"""
        pass

    @staticmethod
    def decode_opus(opus_data: List[bytes]) -> List[bytes]:
        """将Opus音频数据解码为PCM数据"""
        try:
            decoder = opuslib_next.Decoder(16000, 1)
            pcm_data = []
            buffer_size = 960  # 每次处理960个采样点 (60ms at 16kHz)
            
            for i, opus_packet in enumerate(opus_data):
                try:
                    if not opus_packet or len(opus_packet) == 0:
                        continue
                    
                    pcm_frame = decoder.decode(opus_packet, buffer_size)
                    if pcm_frame and len(pcm_frame) > 0:
                        pcm_data.append(pcm_frame)
                        
                except opuslib_next.OpusError as e:
                    logger.bind(tag=TAG).warning(f"Opus解码错误，跳过数据包 {i}: {e}")
                except Exception as e:
                    logger.bind(tag=TAG).error(f"音频处理错误，数据包 {i}: {e}")
            
            return pcm_data
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"音频解码过程发生错误: {e}")
            return []
