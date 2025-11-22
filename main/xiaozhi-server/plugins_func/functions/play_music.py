import os
import re
import time
import random
import difflib
import asyncio
import traceback
from pathlib import Path
from plugins_func.register import register_function, ToolType, ActionResponse, Action, PluginContext
from core.utils.dialogue import Message
from core.providers.tts.dto.dto import SentenceType, ContentType

TAG = __name__

MUSIC_CACHE = {}

play_music_function_desc = {
    "type": "function",
    "function": {
        "name": "play_music",
        "description": "唱歌、听歌、播放音乐的方法。",
        "parameters": {
            "type": "object",
            "properties": {
                "song_name": {
                    "type": "string",
                    "description": "歌曲名称，如果用户没有指定具体歌名则为'random', 明确指定的时返回音乐的名字 示例: ```用户:播放两只老虎\n参数：两只老虎``` ```用户:播放音乐 \n参数：random ```",
                }
            },
            "required": ["song_name"],
        },
    },
}


@register_function("play_music", play_music_function_desc, ToolType.SYSTEM_CTL)
async def play_music(context: PluginContext, song_name: str):
    """播放音乐 - 重构版"""
    try:
        music_intent = (
            f"播放音乐 {song_name}" if song_name != "random" else "随机播放音乐"
        )

        session_context = context.get_context()

        # 检查生命周期状态
        if session_context.lifecycle.is_stopped():
            return ActionResponse(
                action=Action.RESPONSE, result="系统繁忙", response="请稍后再试"
            )

        # 异步处理音乐播放
        asyncio.create_task(handle_music_command(context, music_intent))

        return ActionResponse(
            action=Action.NONE, result="指令已接收", response="正在为您播放音乐"
        )
    except Exception as e:
        from config.logger import setup_logging
        logger = setup_logging()
        logger.bind(tag=TAG).error(f"处理音乐意图错误: {e}")
        return ActionResponse(
            action=Action.RESPONSE, result=str(e), response="播放音乐时出错了"
        )


def _extract_song_name(text):
    """从用户输入中提取歌名"""
    for keyword in ["播放音乐"]:
        if keyword in text:
            parts = text.split(keyword)
            if len(parts) > 1:
                return parts[1].strip()
    return None


def _find_best_match(potential_song, music_files):
    """查找最匹配的歌曲"""
    best_match = None
    highest_ratio = 0

    for music_file in music_files:
        song_name = os.path.splitext(music_file)[0]
        ratio = difflib.SequenceMatcher(None, potential_song, song_name).ratio()
        if ratio > highest_ratio and ratio > 0.4:
            highest_ratio = ratio
            best_match = music_file
    return best_match


def get_music_files(music_dir, music_ext):
    music_dir = Path(music_dir)
    music_files = []
    music_file_names = []
    for file in music_dir.rglob("*"):
        if file.is_file():
            ext = file.suffix.lower()
            if ext in music_ext:
                music_files.append(str(file.relative_to(music_dir)))
                music_file_names.append(
                    os.path.splitext(str(file.relative_to(music_dir)))[0]
                )
    return music_files, music_file_names


def initialize_music_handler(context: PluginContext):
    global MUSIC_CACHE
    if MUSIC_CACHE == {}:
        plugins_config = context.get_config("plugins", {})
        if "play_music" in plugins_config:
            MUSIC_CACHE["music_config"] = plugins_config["play_music"]
            MUSIC_CACHE["music_dir"] = os.path.abspath(
                MUSIC_CACHE["music_config"].get("music_dir", "./music")
            )
            MUSIC_CACHE["music_ext"] = MUSIC_CACHE["music_config"].get(
                "music_ext", (".mp3", ".wav", ".p3")
            )
            MUSIC_CACHE["refresh_time"] = MUSIC_CACHE["music_config"].get(
                "refresh_time", 60
            )
        else:
            MUSIC_CACHE["music_dir"] = os.path.abspath("./music")
            MUSIC_CACHE["music_ext"] = (".mp3", ".wav", ".p3")
            MUSIC_CACHE["refresh_time"] = 60
        # 获取音乐文件列表
        MUSIC_CACHE["music_files"], MUSIC_CACHE["music_file_names"] = get_music_files(
            MUSIC_CACHE["music_dir"], MUSIC_CACHE["music_ext"]
        )
        MUSIC_CACHE["scan_time"] = time.time()
    return MUSIC_CACHE


async def handle_music_command(context: PluginContext, text):
    """处理音乐播放指令"""
    from config.logger import setup_logging
    logger = setup_logging()

    initialize_music_handler(context)
    global MUSIC_CACHE

    clean_text = re.sub(r"[^\w\s]", "", text).strip()
    logger.bind(tag=TAG).debug(f"检查是否是音乐命令: {clean_text}")

    # 尝试匹配具体歌名
    if os.path.exists(MUSIC_CACHE["music_dir"]):
        if time.time() - MUSIC_CACHE["scan_time"] > MUSIC_CACHE["refresh_time"]:
            # 刷新音乐文件列表
            MUSIC_CACHE["music_files"], MUSIC_CACHE["music_file_names"] = (
                get_music_files(MUSIC_CACHE["music_dir"], MUSIC_CACHE["music_ext"])
            )
            MUSIC_CACHE["scan_time"] = time.time()

        potential_song = _extract_song_name(clean_text)
        if potential_song:
            best_match = _find_best_match(potential_song, MUSIC_CACHE["music_files"])
            if best_match:
                logger.bind(tag=TAG).info(f"找到最匹配的歌曲: {best_match}")
                await play_local_music(context, specific_file=best_match)
                return True
    # 检查是否是通用播放音乐命令
    await play_local_music(context)
    return True


def _get_random_play_prompt(song_name):
    """生成随机播放引导语"""
    # 移除文件扩展名
    clean_name = os.path.splitext(song_name)[0]
    prompts = [
        f"正在为您播放，《{clean_name}》",
        f"请欣赏歌曲，《{clean_name}》",
        f"即将为您播放，《{clean_name}》",
        f"现在为您带来，《{clean_name}》",
        f"让我们一起聆听，《{clean_name}》",
        f"接下来请欣赏，《{clean_name}》",
        f"此刻为您献上，《{clean_name}》",
    ]
    return random.choice(prompts)


async def play_local_music(context: PluginContext, specific_file=None):
    """播放本地音乐文件 - 重构版"""
    from config.logger import setup_logging
    logger = setup_logging()

    global MUSIC_CACHE
    try:
        if not os.path.exists(MUSIC_CACHE["music_dir"]):
            logger.bind(tag=TAG).error(
                f"音乐目录不存在: " + MUSIC_CACHE["music_dir"]
            )
            return

        # 确保路径正确性
        if specific_file:
            selected_music = specific_file
            music_path = os.path.join(MUSIC_CACHE["music_dir"], specific_file)
        else:
            if not MUSIC_CACHE["music_files"]:
                logger.bind(tag=TAG).error("未找到MP3音乐文件")
                return
            selected_music = random.choice(MUSIC_CACHE["music_files"])
            music_path = os.path.join(MUSIC_CACHE["music_dir"], selected_music)

        if not os.path.exists(music_path):
            logger.bind(tag=TAG).error(f"选定的音乐文件不存在: {music_path}")
            return

        text = _get_random_play_prompt(selected_music)

        # 获取服务
        session_context = context.get_context()
        tts_orchestrator = context.get_service('tts_orchestrator')
        ws_transport = context.get_service('websocket_transport')

        # 发送STT消息
        await ws_transport.send_json(session_context.session_id, {
            "type": "stt",
            "text": text
        })

        # 保存对话
        session_context.dialogue.put(Message(role="assistant", content=text))

        intent_type = session_context.get_config('Intent.type')

        # 根据intent类型添加消息
        if intent_type == "intent_llm":
            await tts_orchestrator.add_message(
                session_id=context.session_id,
                sentence_type=SentenceType.FIRST,
                content_type=ContentType.ACTION,
            )

        await tts_orchestrator.add_message(
            session_id=context.session_id,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.TEXT,
            content_detail=text,
        )

        await tts_orchestrator.add_message(
            session_id=context.session_id,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.FILE,
            content_file=music_path,
        )

        if intent_type == "intent_llm":
            await tts_orchestrator.add_message(
                session_id=context.session_id,
                sentence_type=SentenceType.LAST,
                content_type=ContentType.ACTION,
            )

    except Exception as e:
        logger.bind(tag=TAG).error(f"播放音乐失败: {str(e)}")
        logger.bind(tag=TAG).error(f"详细错误: {traceback.format_exc()}")
