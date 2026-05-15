import time
import json
import uuid
import random
import asyncio

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler
from core.utils.dialogue import Message
from core.utils.util import audio_to_data
from core.providers.tts.dto.dto import SentenceType, ContentType, TTSMessageDTO
from core.utils.wakeup_word import WakeupWordsConfig
from core.handle.sendAudioHandle import sendAudioMessage, send_tts_message
from core.utils.util import remove_punctuation_and_length, opus_datas_to_wav_bytes
from core.providers.tools.device_mcp import MCPClient, send_mcp_initialize_message

# 预加载 LLM 工具模块和提供者模块
# 避免唤醒词快速路径初始化 SLM 时，与后台 initialize_modules 产生循环导入冲突
import importlib as _importlib
import sys as _sys
import core.utils.llm  # noqa: F401 — 触发模块注册到 sys.modules
# 遍历所有 LLM 提供者目录，预加载到 sys.modules
import os as _os
_llm_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "providers", "llm")
if _os.path.isdir(_llm_dir):
    for _name in _os.listdir(_llm_dir):
        _mod_path = _os.path.join(_llm_dir, _name, f"{_name}.py")
        if _os.path.isfile(_mod_path):
            _fq = f"core.providers.llm.{_name}.{_name}"
            if _fq not in _sys.modules:
                try:
                    _sys.modules[_fq] = _importlib.import_module(_fq)
                except Exception:
                    pass

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

# SLM 唤醒词回复的系统提示词模板
# 从 agent-base-prompt.txt 精简而来，保留角色风格和语言规则，剔除工具/TTS格式等无关内容
SLM_WAKEUP_SYSTEM_PROMPT = """用户跟你打招呼了，请用{language}回应，简短自然。
{identity}
规则：
- 说一两句话表示你在，风格随意，像朋友之间，不要太长，20字以内
- 不要反问、不要追问、不要展开话题
- 不要用"烦心事"、"有趣的事"、"好玩的事"、"综上所述"
- 不要念出给你的编号
回复："""

# 创建全局的唤醒词配置管理器
wakeup_words_config = WakeupWordsConfig()

# 用于防止并发调用wakeupWordsResponse的锁
_wakeup_response_lock = asyncio.Lock()


async def handleHelloMessage(conn: "ConnectionHandler", msg_json):
    """处理hello消息"""
    audio_params = msg_json.get("audio_params")
    if audio_params:
        format = audio_params.get("format")
        conn.logger.bind(tag=TAG).debug(f"客户端音频格式: {format}")
        conn.audio_format = format
        conn.welcome_msg["audio_params"] = audio_params
    features = msg_json.get("features")
    if features:
        conn.logger.bind(tag=TAG).debug(f"客户端特性: {features}")
        conn.features = features
        if features.get("mcp"):
            conn.logger.bind(tag=TAG).debug("客户端支持MCP")
            conn.mcp_client = MCPClient()
            # 发送初始化
            asyncio.create_task(send_mcp_initialize_message(conn))

    await conn.websocket.send(json.dumps(conn.welcome_msg))


def _build_slm_prompt(conn: "ConnectionHandler") -> str:
    """构建 SLM 唤醒词回复的系统提示词"""
    # 提取用户智能体的人设
    identity = ""
    user_prompt = conn.config.get("prompt", "")
    if user_prompt:
        identity = f"<identity>\n{user_prompt}\n</identity>"

    # 获取语言配置，与大模型保持一致
    language = (
        conn.config.get("TTS", {})
        .get(conn.config.get("selected_module", {}).get("TTS", ""), {})
        .get("language")
        or "中文"
    )

    return SLM_WAKEUP_SYSTEM_PROMPT.format(
        language=language,
        identity=identity,
    )


async def _generate_slm_response(conn: "ConnectionHandler") -> str | None:
    """调用 SLM 生成唤醒词回复，失败返回 None"""
    if not conn.slm:
        return None

    try:
        system_prompt = _build_slm_prompt(conn)
        user_msg = random.choice([
            "用户来了，打个招呼吧，自然点。",
            "嘿，用户在呢，随意应一下就行。",
            "用户喊你啦，用你自己的方式回应。",
            "叮咚，用户找你，简单回应一下。",
            "用户跟你打招呼了，随意回一句。",
            "有人叫你名字，应一声吧。",
            "用户跟你说话了，简单回一下。",
            "打个招呼吧，用你的风格。",
            "用户在你旁边，说句话吧。",
            "随便打个招呼，别太正式。",
        ])
        result = await asyncio.wait_for(
            asyncio.to_thread(
                conn.slm.response_no_stream,
                system_prompt,
                user_msg,
                max_tokens=25,
                temperature=0.9,
            ),
            timeout=5.0,
        )
        if result and len(result.strip()) > 0:
            conn.logger.bind(tag=TAG).info(f"SLM生成唤醒词回复: {result.strip()}")
            return result.strip()
        return None
    except asyncio.TimeoutError:
        conn.logger.bind(tag=TAG).warning("SLM生成唤醒词回复超时，回退到固定短语")
        return None
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"SLM生成唤醒词回复失败: {e}")
        return None


async def _send_wakeup_response(conn: "ConnectionHandler", response_text: str):
    """将回复文本通过流式 TTS 队列发送给设备"""
    conn.client_abort = False
    sentence_id = str(uuid.uuid4().hex)
    conn.sentence_id = sentence_id

    conn.logger.bind(tag=TAG).info(f"播放唤醒词回复: {response_text}")

    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=sentence_id,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
    )
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=sentence_id,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.TEXT,
            content_detail=response_text,
        )
    )
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=sentence_id,
            sentence_type=SentenceType.LAST,
            content_type=ContentType.ACTION,
        )
    )

    conn.dialogue.put(Message(role="assistant", content=response_text))


async def _wakeup_ensure_prompt(conn: "ConnectionHandler"):
    """唤醒词快速路径：初始化提示词（SLM 生成回复依赖 prompt）"""
    if conn.prompt is not None:
        return
    user_prompt = conn.config.get("prompt")
    if user_prompt:
        quick_prompt = conn.prompt_manager.get_quick_prompt(user_prompt)
        conn.change_system_prompt(quick_prompt)


async def _wakeup_ensure_slm(conn: "ConnectionHandler"):
    """唤醒词快速路径：按需初始化 SLM"""
    if conn.slm is not None:
        return
    try:
        await asyncio.get_running_loop().run_in_executor(None, conn._initialize_slm)
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"唤醒词快速初始化SLM失败: {e}")


async def _wakeup_ensure_tts(conn: "ConnectionHandler"):
    """唤醒词快速路径：按需初始化 TTS + 音频通道"""
    # 检查 TTS 实例是否已创建且音频通道已打开
    if conn.tts is not None:
        tts_thread = getattr(conn.tts, 'tts_priority_thread', None)
        if tts_thread is not None and tts_thread.is_alive():
            return  # TTS 已就绪，无需重复初始化

    def _do_init():
        if conn.tts is None:
            tts_instance = conn._initialize_tts()
            conn.tts = tts_instance
        # 打开音频通道（即使 TTS 已存在但通道未打开）
        if conn.tts is not None:
            tts_thread = getattr(conn.tts, 'tts_priority_thread', None)
            if tts_thread is None or not tts_thread.is_alive():
                future = asyncio.run_coroutine_threadsafe(
                    conn.tts.open_audio_channels(conn), conn.loop
                )
                future.result(timeout=5)  # 等待音频通道打开完成

    try:
        await asyncio.get_running_loop().run_in_executor(None, _do_init)
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"唤醒词快速初始化TTS失败: {e}")


async def checkWakeupWords(conn: "ConnectionHandler", text):
    enable_wakeup_words_response_cache = conn.config[
        "enable_wakeup_words_response_cache"
    ]

    _, filtered_text = remove_punctuation_and_length(text)
    if filtered_text not in conn.config.get("wakeup_words"):
        return False

    conn.just_woken_up = True

    # 唤醒词快速路径：按需初始化 提示词 → SLM → TTS
    # 后台 _initialize_components 会跳过已初始化的组件，不会冲突
    await _wakeup_ensure_prompt(conn)
    await _wakeup_ensure_slm(conn)
    await _wakeup_ensure_tts(conn)

    if conn.tts is None:
        return False

    # SLM 路径：生成个性化回复
    if conn.slm:
        slm_response = await _generate_slm_response(conn)
        if slm_response:
            await send_tts_message(conn, "start")
            await _send_wakeup_response(conn, slm_response)
            return True
        # SLM 生成失败，回退到固定短语缓存逻辑
        conn.logger.bind(tag=TAG).info("SLM不可用，回退到固定短语唤醒词回复")

    if not enable_wakeup_words_response_cache:
        return False

    # 固定短语缓存路径（无 SLM 或 SLM 失败时的降级逻辑）
    voice = getattr(conn.tts, "voice", "default")
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
    opus_packets = await audio_to_data(response.get("file_path"), use_cache=False)
    # 播放唤醒词回复
    conn.client_abort = False

    # 将唤醒词回复视为新会话，生成新的 sentence_id，确保流控器重置
    conn.sentence_id = str(uuid.uuid4().hex)

    conn.logger.bind(tag=TAG).info(f"播放唤醒词回复: {response.get('text')}")
    await sendAudioMessage(conn, SentenceType.FIRST, opus_packets, response.get("text"))
    await sendAudioMessage(conn, SentenceType.LAST, [], None)

    # 补充对话
    conn.dialogue.put(Message(role="assistant", content=response.get("text")))

    # 检查是否需要更新唤醒词回复
    if time.time() - response.get("time", 0) > WAKEUP_CONFIG["refresh_time"]:
        if not _wakeup_response_lock.locked():
            asyncio.create_task(wakeupWordsResponse(conn))
    return True


async def wakeupWordsResponse(conn: "ConnectionHandler"):
    if not conn.tts:
        return

    try:
        # 尝试获取锁，如果获取不到就返回
        if not await _wakeup_response_lock.acquire():
            return

        # 从预定义回复列表中随机选择一个回复
        result = random.choice(WAKEUP_CONFIG["responses"])
        if not result or len(result) == 0:
            return

        # 生成TTS音频
        tts_result = await asyncio.to_thread(conn.tts.to_tts, result)
        if not tts_result:
            return

        # 获取当前音色
        voice = getattr(conn.tts, "voice", "default")

        # 使用链接的sample_rate
        wav_bytes = opus_datas_to_wav_bytes(tts_result, sample_rate=conn.sample_rate)
        file_path = wakeup_words_config.generate_file_path(voice)
        with open(file_path, "wb") as f:
            f.write(wav_bytes)
        # 更新配置
        wakeup_words_config.update_wakeup_response(voice, file_path, result)
    finally:
        # 确保在任何情况下都释放锁
        if _wakeup_response_lock.locked():
            _wakeup_response_lock.release()
