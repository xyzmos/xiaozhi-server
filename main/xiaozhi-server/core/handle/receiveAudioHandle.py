import time
import json
import asyncio
from config.logger import setup_logging
from core.utils.util import audio_to_data
from core.utils import textUtils
from core.infrastructure.event.event_types import (
    AudioDataReceivedEvent,
    ClientAbortEvent,
)
from core.handle.intentHandler import handle_user_intent
from core.utils.output_counter import check_device_output_limit
from core.providers.tts.dto.dto import SentenceType
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
            conn = self._get_session_context(session_id)
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
        # 从会话上下文获取服务
        session_id = context.session_id

        # 解析服务
        vad = context.container.resolve("vad")
        asr_service = context.container.resolve("asr_service", session_id=session_id)

        # 当前片段是否有人说话
        have_voice = vad.is_vad(context, audio)

        # 如果设备刚刚被唤醒，短暂忽略VAD检测
        if hasattr(context, "just_woken_up") and context.just_woken_up:
            have_voice = False
            # 设置一个短暂延迟后恢复VAD检测
            if hasattr(asr_service, "clear_buffer"):
                asr_service.clear_buffer()
            if (
                not hasattr(context, "vad_resume_task")
                or context.vad_resume_task.done()
            ):
                context.vad_resume_task = asyncio.create_task(
                    resume_vad_detection(context)
                )
            return

        # manual 模式下不打断正在播放的内容
        if have_voice:
            if context.client_is_speaking and context.client_listen_mode != "manual":
                event_bus = context.container.resolve("event_bus")
                await event_bus.publish(
                    ClientAbortEvent(
                        session_id=session_id,
                        timestamp=time.time(),
                        reason="voice_detected",
                    )
                )

        # 设备长时间空闲检测，用于say goodbye
        await no_voice_close_connect(context, have_voice)

        # 接收音频
        await asr_service.receive_audio(context, audio, have_voice)

    except Exception as e:
        logger.bind(tag=TAG).error(f"处理音频消息失败: {e}", exc_info=True)


async def resume_vad_detection(context):
    """恢复VAD检测

    Args:
        context: SessionContext 会话上下文
    """
    # 等待2秒后恢复VAD检测
    await asyncio.sleep(2)
    context.just_woken_up = False


async def startToChat(context, text):
    """开始对话处理

    Args:
        context: SessionContext 会话上下文
        text: 用户输入文本
    """
    logger = setup_logging()
    # 检查输入是否是JSON格式（包含说话人信息）
    speaker_name = None
    actual_text = text

    try:
        # 尝试解析JSON格式的输入
        if text.strip().startswith("{") and text.strip().endswith("}"):
            data = json.loads(text)
            if "speaker" in data and "content" in data:
                speaker_name = data["speaker"]
                actual_text = data["content"]
                logger.bind(tag=TAG).info(f"解析到说话人信息: {speaker_name}")

                # 直接使用JSON格式的文本，不解析
                actual_text = text
    except (json.JSONDecodeError, KeyError):
        # 如果解析失败，继续使用原始文本
        pass

    # 保存说话人信息到连接对象
    if speaker_name:
        context.current_speaker = speaker_name
    else:
        context.current_speaker = None

    if context.need_bind:
        await check_bind_device(context)
        return

    # 如果当日的输出字数大于限定的字数
    if context.max_output_size > 0:
        if check_device_output_limit(
            context.headers.get("device-id"), context.max_output_size
        ):
            await max_out_size(context)
            return
    # manual 模式下不打断正在播放的内容
    if context.client_is_speaking and context.client_listen_mode != "manual":
        event_bus = context.container.resolve("event_bus")
        await event_bus.publish(
            ClientAbortEvent(
                session_id=context.session_id,
                timestamp=time.time(),
                reason="new_user_input",
            )
        )

    # 首先进行意图分析，使用实际文本内容
    intent_handled = await handle_user_intent(context, actual_text)

    if intent_handled:
        # 如果意图已被处理，不再进行聊天
        return

    # 意图未被处理，继续常规聊天流程，使用实际文本内容
    ws_transport = context.container.resolve("websocket_transport")
    await ws_transport.send_json(
        context.session_id,
        {
            "type": "stt",
            "text": textUtils.check_emoji(actual_text),
            "session_id": context.session_id,
        },
    )

    # 通过对话服务处理
    dialogue_service = context.container.resolve("dialogue_service")
    # 使用异步任务而非线程池
    asyncio.create_task(
        dialogue_service.process_user_input(context.session_id, actual_text)
    )


async def no_voice_close_connect(context, have_voice):
    """检测无语音连接超时

    Args:
        context: SessionContext 会话上下文
        have_voice: 是否有语音
    """
    logger = setup_logging()
    if have_voice:
        context.last_activity_time = time.time() * 1000
        return
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
                logger.bind(tag=TAG).info("结束对话，无需发送结束提示语")
                await context.close()
                return
            prompt = end_prompt.get("prompt")
            if not prompt:
                prompt = "请你以```时间过得真快```未来头，用富有感情、依依不舍的话来结束这场对话吧。！"
            await startToChat(context, prompt)


async def max_out_size(context):
    """播放超出最大输出字数的提示

    Args:
        context: SessionContext 会话上下文
    """
    logger = setup_logging()
    context.client_abort = False
    text = "不好意思，我现在有点事情要忙，明天这个时候我们再聊，约好了哦！明天不见不散，拜拜！"

    ws_transport = context.container.resolve("websocket_transport")
    await ws_transport.send_json(
        context.session_id,
        {
            "type": "stt",
            "text": textUtils.check_emoji(text),
            "session_id": context.session_id,
        },
    )

    file_path = "config/assets/max_output_size.wav"
    opus_packets = audio_to_data(file_path)

    # 通过 TTS 编排服务发送
    try:
        from core.providers.tts.dto.dto import TTSMessageDTO, ContentType

        tts_provider = context.container.resolve("tts", session_id=context.session_id)
        # 直接将音频数据放入队列
        message = TTSMessageDTO(
            sentence_id=context.sentence_id if hasattr(context, "sentence_id") else "",
            sentence_type=SentenceType.LAST,
            content_type=ContentType.FILE,
            audio_data=opus_packets,
            content_detail=text,
        )
        tts_provider.tts_text_queue.put(message)
    except Exception as e:
        logger.bind(tag=TAG).error(f"通过容器发送 TTS 失败: {e}")

    context.close_after_chat = True


async def check_bind_device(context):
    """检查设备绑定

    Args:
        context: SessionContext 会话上下文
    """
    logger = setup_logging()
    # 通过容器获取 TTS 服务
    from core.providers.tts.dto.dto import TTSMessageDTO, ContentType

    try:
        tts_provider = context.container.resolve("tts", session_id=context.session_id)
    except Exception as e:
        logger.bind(tag=TAG).error(f"无法获取 TTS 服务: {e}")
        return

    ws_transport = context.container.resolve("websocket_transport")

    if context.bind_code:
        # 确保bind_code是6位数字
        if len(context.bind_code) != 6:
            logger.bind(tag=TAG).error(f"无效的绑定码格式: {context.bind_code}")
            text = "绑定码格式错误，请检查配置。"
            await ws_transport.send_json(
                context.session_id,
                {
                    "type": "stt",
                    "text": textUtils.check_emoji(text),
                    "session_id": context.session_id,
                },
            )
            return

        text = f"请登录控制面板，输入{context.bind_code}，绑定设备。"
        await ws_transport.send_json(
            context.session_id,
            {
                "type": "stt",
                "text": textUtils.check_emoji(text),
                "session_id": context.session_id,
            },
        )

        # 播放提示音
        music_path = "config/assets/bind_code.wav"
        opus_packets = audio_to_data(music_path)
        message = TTSMessageDTO(
            sentence_id=context.sentence_id if hasattr(context, "sentence_id") else "",
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.FILE,
            audio_data=opus_packets,
            content_detail=text,
        )
        tts_provider.tts_text_queue.put(message)

        # 逐个播放数字
        for i in range(6):
            try:
                digit = context.bind_code[i]
                num_path = f"config/assets/bind_code/{digit}.wav"
                num_packets = audio_to_data(num_path)
                message = TTSMessageDTO(
                    sentence_id=(
                        context.sentence_id if hasattr(context, "sentence_id") else ""
                    ),
                    sentence_type=SentenceType.MIDDLE,
                    content_type=ContentType.FILE,
                    audio_data=num_packets,
                )
                tts_provider.tts_text_queue.put(message)
            except Exception as e:
                logger.bind(tag=TAG).error(f"播放数字音频失败: {e}")
                continue

        # 结束消息
        message = TTSMessageDTO(
            sentence_id=context.sentence_id if hasattr(context, "sentence_id") else "",
            sentence_type=SentenceType.LAST,
            content_type=ContentType.ACTION,
        )
        tts_provider.tts_text_queue.put(message)
    else:
        # 播放未绑定提示
        context.client_abort = False
        text = f"没有找到该设备的版本信息，请正确配置 OTA地址，然后重新编译固件。"
        await ws_transport.send_json(
            context.session_id,
            {
                "type": "stt",
                "text": textUtils.check_emoji(text),
                "session_id": context.session_id,
            },
        )
        music_path = "config/assets/bind_not_found.wav"
        opus_packets = audio_to_data(music_path)
        message = TTSMessageDTO(
            sentence_id=context.sentence_id if hasattr(context, "sentence_id") else "",
            sentence_type=SentenceType.LAST,
            content_type=ContentType.FILE,
            audio_data=opus_packets,
            content_detail=text,
        )
        tts_provider.tts_text_queue.put(message)


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
