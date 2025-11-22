"""Hello消息处理器 - 事件驱动架构重构版"""

import time
import json
import random
import asyncio
from typing import Dict, Any

from config.logger import setup_logging
from core.utils.dialogue import Message
from core.utils.util import audio_to_data
from core.providers.tts.dto.dto import SentenceType
from core.utils.wakeup_word import WakeupWordsConfig
from core.utils.util import remove_punctuation_and_length, opus_datas_to_wav_bytes
from core.infrastructure.event.event_types import TextMessageReceivedEvent
from core.infrastructure.di.container import DIContainer
from core.infrastructure.event.event_bus import EventBus
from core.providers.tools.device_mcp import MCPClient
from core.providers.tools.device_mcp.mcp_handler import (
    send_mcp_initialize_message,
    send_mcp_tools_list_request,
)

TAG = __name__

WAKEUP_CONFIG = {
    "refresh_time": 10,
    "responses": [
        "我一直都在呢，您请说。",
        "在的呢，请随时吩咐我。",
        "来啦来啦，请告诉我吧。",
        "您请说，我正听着。",
        "请您讲话，我准备好了。",
        "请您说出指令吧。",
        "我认真听着呢，请讲。",
        "请问您需要什么帮助？",
        "我在这里，等候您的指令。",
    ],
}

# 创建全局的唤醒词配置管理器
wakeup_words_config = WakeupWordsConfig()

# 用于防止并发调用wakeupWordsResponse的锁
_wakeup_response_lock = asyncio.Lock()


class HelloMessageHandler:
    """Hello消息处理器 - 完全事件驱动"""

    def __init__(self, container: DIContainer, event_bus: EventBus):
        self.container = container
        self.event_bus = event_bus
        self.logger = setup_logging()

    async def handle(self, event: TextMessageReceivedEvent):
        """处理文本消息，检查是否是hello消息"""
        try:
            msg_json = json.loads(event.content)
            if msg_json.get("type") != "hello":
                return

            await self._handle_hello_message(event.session_id, msg_json)
        except json.JSONDecodeError:
            pass

    async def _handle_hello_message(self, session_id: str, msg_json: Dict[str, Any]):
        """处理hello消息 - 完全通过服务和上下文"""
        # 获取会话上下文和传输层
        context = self.container.resolve('session_context', session_id=session_id)
        ws_transport = self.container.resolve('websocket_transport')

        audio_params = msg_json.get("audio_params")
        if audio_params:
            format_type = audio_params.get("format")
            self.logger.bind(tag=TAG).debug(f"客户端音频格式: {format_type}")
            context.audio_format = format_type
            context.welcome_msg["audio_params"] = audio_params

        features = msg_json.get("features")
        if features:
            self.logger.bind(tag=TAG).debug(f"客户端特性: {features}")
            context.features = features
            if features.get("mcp"):
                self.logger.bind(tag=TAG).debug("客户端支持MCP")
                context.mcp_client = MCPClient()
                # 发送MCP初始化消息
                asyncio.create_task(self._send_mcp_init(session_id))

        # 通过传输层发送欢迎消息
        await ws_transport.send_json(session_id, context.welcome_msg)

    async def _send_mcp_init(self, session_id: str):
        """发送MCP初始化消息 - 使用标准的MCP handler函数"""
        try:
            context = self.container.resolve('session_context', session_id=session_id)

            if not context.mcp_client:
                return

            # 使用标准的MCP初始化和工具列表请求函数
            await send_mcp_initialize_message(context)
            await send_mcp_tools_list_request(context)

            self.logger.bind(tag=TAG).debug(f"MCP初始化消息已发送: {session_id}")
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"发送MCP初始化消息失败: {e}")


def register_hello_handler(container: DIContainer, event_bus: EventBus):
    """注册Hello消息处理器到事件总线"""
    handler = HelloMessageHandler(container, event_bus)
    event_bus.subscribe(TextMessageReceivedEvent, handler.handle)
    return handler


async def checkWakeupWords(context, text):
    """检查唤醒词并返回缓存的回复 - 通过容器和服务处理

    Args:
        context: SessionContext 会话上下文
        text: 识别的文本
    """
    logger = setup_logging()
    enable_wakeup_words_response_cache = context.get_config("enable_wakeup_words_response_cache", False)

    # 等待tts初始化，最多等待3秒
    start_time = time.time()
    tts = None
    while time.time() - start_time < 3:
        try:
            tts = context.container.resolve('tts', session_id=context.session_id)
            if tts:
                break
        except Exception:
            pass
        await asyncio.sleep(0.1)

    if not tts:
        return False

    if not enable_wakeup_words_response_cache:
        return False

    _, filtered_text = remove_punctuation_and_length(text)
    if filtered_text not in context.get_config("wakeup_words", []):
        return False

    context.just_woken_up = True

    # 获取当前音色
    voice = getattr(tts, "voice", "default")
    if not voice:
        voice = "default"

    # 获取唤醒词回复配置
    response = wakeup_words_config.get_wakeup_response(voice)
    if not response or not response.get("file_path"):
        response = {
            "voice": "default",
            "file_path": "config/assets/wakeup_words_short.wav",
            "time": 0,
            "text": "我在这里哦！",
        }

    # 获取音频数据
    opus_packets = audio_to_data(response.get("file_path"))
    context.client_abort = False

    logger.bind(tag=TAG).info(f"播放唤醒词回复: {response.get('text')}")

    # 使用 AudioSendHandler 发送音频
    from core.handle.sendAudioHandle import AudioSendHandler
    audio_handler = AudioSendHandler(context.container, context.container.resolve('event_bus'))
    await audio_handler.send_audio_message(
        session_id=context.session_id,
        sentence_type=SentenceType.FIRST,
        audios=opus_packets,
        text=response.get("text")
    )
    await audio_handler.send_audio_message(
        session_id=context.session_id,
        sentence_type=SentenceType.LAST,
        audios=[],
        text=None
    )

    # 补充对话
    context.dialogue.put(Message(role="assistant", content=response.get("text")))

    # 检查是否需要更新唤醒词回复
    if time.time() - response.get("time", 0) > WAKEUP_CONFIG["refresh_time"]:
        if not _wakeup_response_lock.locked():
            asyncio.create_task(wakeupWordsResponse(context))
    return True


async def wakeupWordsResponse(context):
    """生成新的唤醒词回复并缓存

    Args:
        context: SessionContext 会话上下文
    """
    logger = setup_logging()
    # 通过容器获取 TTS 服务
    try:
        tts = context.container.resolve('tts', session_id=context.session_id)
    except Exception:
        return

    if not tts:
        return

    try:
        if not await _wakeup_response_lock.acquire():
            return

        result = random.choice(WAKEUP_CONFIG["responses"])
        if not result or len(result) == 0:
            return

        tts_result = await asyncio.to_thread(tts.to_tts, result)
        if not tts_result:
            return

        voice = getattr(tts, "voice", "default")

        wav_bytes = opus_datas_to_wav_bytes(tts_result, sample_rate=16000)
        file_path = wakeup_words_config.generate_file_path(voice)
        with open(file_path, "wb") as f:
            f.write(wav_bytes)
        wakeup_words_config.update_wakeup_response(voice, file_path, result)
    finally:
        if _wakeup_response_lock.locked():
            _wakeup_response_lock.release()
