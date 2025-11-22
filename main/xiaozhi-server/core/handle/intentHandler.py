import json
import uuid
import asyncio
from config.logger import setup_logging
from core.utils import textUtils
from core.utils.dialogue import Message
from core.providers.tts.dto.dto import ContentType
from core.handle.helloHandle import checkWakeupWords
from plugins_func.register import Action, ActionResponse
from core.utils.util import remove_punctuation_and_length
from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType
from core.infrastructure.event.event_types import (
    TextMessageReceivedEvent,
    IntentRecognizedEvent,
)
from core.infrastructure.di.container import DIContainer

TAG = __name__


# ==================== 新架构：事件驱动模式 ====================


class IntentMessageHandler:
    """意图消息处理器 - 使用事件监听器模式"""

    def __init__(self, container: DIContainer):
        """初始化意图消息处理器

        Args:
            container: 依赖注入容器
        """
        self.container = container
        self.logger = setup_logging()
        self.event_bus = container.resolve("event_bus")

        # 注意: 不再订阅 TextMessageReceivedEvent，由 TextMessageHandler 负责解析并调用
        # TextMessageReceivedEvent 是原始的 WebSocket 文本消息事件
        # 意图处理由 textHandle.py 中的 _process_user_text 方法通过直接调用 handle_user_intent 触发
        self.logger.bind(tag=TAG).info("意图消息处理器已初始化")

    async def on_text_received(self, event: TextMessageReceivedEvent):
        """处理文本消息接收事件

        Args:
            event: 文本消息接收事件
        """
        session_id = event.session_id
        text = event.content

        try:
            # 从容器解析会话上下文
            context = self._get_session_context(session_id)
            if not context:
                self.logger.bind(tag=TAG).warning(f"会话 {session_id} 未找到")
                return

            # 调用原有的意图处理逻辑
            intent_handled = await handle_user_intent(context, text)

            # 如果识别到意图，发布意图识别事件
            if intent_handled:
                intent_event = IntentRecognizedEvent(
                    session_id=session_id, intent=text, confidence=1.0
                )
                await self.event_bus.publish(intent_event)

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"处理意图消息时出错: {e}", exc_info=True)

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


async def handle_user_intent(context, text):
    logger = setup_logging()
    logger.bind(tag=TAG).debug(f"handle_user_intent 被调用: text={text}")

    # 预处理输入文本，处理可能的JSON格式
    try:
        if text.strip().startswith("{") and text.strip().endswith("}"):
            parsed_data = json.loads(text)
            if isinstance(parsed_data, dict) and "content" in parsed_data:
                text = parsed_data["content"]  # 提取content用于意图分析
                context.current_speaker = parsed_data.get("speaker")  # 保留说话人信息
    except (json.JSONDecodeError, TypeError):
        pass

    # 检查是否有明确的退出命令
    _, filtered_text = remove_punctuation_and_length(text)
    logger.bind(tag=TAG).debug(f"过滤后的文本: {filtered_text}")

    if await check_direct_exit(context, filtered_text):
        logger.bind(tag=TAG).debug("检测到退出命令")
        return True

    # 检查是否是唤醒词
    wakeup_result = await checkWakeupWords(context, filtered_text)
    logger.bind(tag=TAG).debug(f"唤醒词检查结果: {wakeup_result}")
    if wakeup_result:
        return True

    logger.bind(tag=TAG).debug(f"context.intent_type = {context.intent_type}")
    if context.intent_type == "function_call":
        # 使用支持function calling的聊天方法,不再进行意图分析
        logger.bind(tag=TAG).warning(
            f"intent_type 是 function_call，跳过意图分析，直接返回 False"
        )
        return False

    # 使用LLM进行意图分析（仅在非function_call模式下）
    logger.bind(tag=TAG).debug("开始意图分析")
    intent_result = await analyze_intent_with_llm(context, text)
    if not intent_result:
        logger.bind(tag=TAG).warning("意图分析返回空结果")
        return False
    # 会话开始时生成sentence_id
    context.sentence_id = str(uuid.uuid4().hex)
    # 处理各种意图
    return await process_intent_result(context, intent_result, text)


async def check_direct_exit(context, text):
    """检查是否有明确的退出命令"""
    logger = setup_logging()
    _, text = remove_punctuation_and_length(text)
    cmd_exit = context.cmd_exit
    for cmd in cmd_exit:
        if text == cmd:
            logger.bind(tag=TAG).info(f"识别到明确的退出命令: {text}")
            ws_transport = context.container.resolve("websocket_transport")
            await ws_transport.send_json(
                context.session_id,
                {
                    "type": "stt",
                    "text": textUtils.check_emoji(text),
                    "session_id": context.session_id,
                },
            )
            await context.close()
            return True
    return False


async def analyze_intent_with_llm(context, text):
    """使用LLM分析用户意图"""
    logger = setup_logging()
    if not hasattr(context, "intent") or not context.intent:
        logger.bind(tag=TAG).warning("意图识别服务未初始化")
        return None

    # 对话历史记录
    dialogue = context.dialogue
    try:
        intent_result = await context.intent.detect_intent(
            context, dialogue.dialogue, text
        )
        return intent_result
    except Exception as e:
        logger.bind(tag=TAG).error(f"意图识别失败: {str(e)}")

    return None


async def process_intent_result(context, intent_result, original_text):
    """处理意图识别结果"""
    logger = setup_logging()
    try:
        # 尝试将结果解析为JSON
        intent_data = json.loads(intent_result)

        # 检查是否有function_call
        if "function_call" in intent_data:
            # 直接从意图识别获取了function_call
            logger.bind(tag=TAG).debug(
                f"检测到function_call格式的意图结果: {intent_data['function_call']['name']}"
            )
            function_name = intent_data["function_call"]["name"]
            if function_name == "continue_chat":
                return False

            if function_name == "result_for_context":
                ws_transport = context.container.resolve("websocket_transport")
                await ws_transport.send_json(
                    context.session_id,
                    {
                        "type": "stt",
                        "text": textUtils.check_emoji(original_text),
                        "session_id": context.session_id,
                    },
                )
                context.client_abort = False

                async def process_context_result():
                    context.dialogue.put(Message(role="user", content=original_text))

                    from core.utils.current_time import get_current_time_info

                    current_time, today_date, today_weekday, lunar_date = (
                        get_current_time_info()
                    )

                    # 构建带上下文的基础提示
                    context_prompt = f"""当前时间：{current_time}
                                        今天日期：{today_date} ({today_weekday})
                                        今天农历：{lunar_date}

                                        请根据以上信息回答用户的问题：{original_text}"""

                    response = context.intent.replyResult(context_prompt, original_text)
                    speak_txt(context, response)

                # 使用异步任务
                asyncio.create_task(process_context_result())
                return True

            function_args = {}
            if "arguments" in intent_data["function_call"]:
                function_args = intent_data["function_call"]["arguments"]
                if function_args is None:
                    function_args = {}
            # 确保参数是字符串格式的JSON
            if isinstance(function_args, dict):
                function_args = json.dumps(function_args)

            function_call_data = {
                "name": function_name,
                "id": str(uuid.uuid4().hex),
                "arguments": function_args,
            }

            ws_transport = context.container.resolve("websocket_transport")
            await ws_transport.send_json(
                context.session_id,
                {
                    "type": "stt",
                    "text": textUtils.check_emoji(original_text),
                    "session_id": context.session_id,
                },
            )
            context.client_abort = False

            # 使用异步任务处理函数调用
            async def process_function_call_async():
                context.dialogue.put(Message(role="user", content=original_text))

                # 使用统一工具处理器处理所有工具调用
                try:
                    result = await context.func_handler.handle_llm_function_call(
                        context, function_call_data
                    )
                except Exception as e:
                    logger.bind(tag=TAG).error(f"工具调用失败: {e}")
                    result = ActionResponse(
                        action=Action.ERROR, result=str(e), response=str(e)
                    )

                if result:
                    if result.action == Action.RESPONSE:
                        text = result.response
                        if text is not None:
                            speak_txt(context, text)
                    elif result.action == Action.REQLLM:
                        text = result.result
                        context.dialogue.put(Message(role="tool", content=text))
                        llm_result = context.intent.replyResult(text, original_text)
                        if llm_result is None:
                            llm_result = text
                        speak_txt(context, llm_result)
                    elif (
                        result.action == Action.NOTFOUND
                        or result.action == Action.ERROR
                    ):
                        text = result.result
                        if text is not None:
                            speak_txt(context, text)
                    elif function_name != "play_music":
                        text = result.response
                        if text is None:
                            text = result.result
                        if text is not None:
                            speak_txt(context, text)

            asyncio.create_task(process_function_call_async())
            return True
        return False
    except json.JSONDecodeError as e:
        logger.bind(tag=TAG).error(f"处理意图结果时出错: {e}")
        return False


def speak_txt(context, text):
    """播放文本 - 通过容器解析服务"""
    logger = setup_logging()
    # 通过容器获取 TTS 服务
    try:
        tts_service = context.container.resolve("tts", session_id=context.session_id)
    except Exception:
        return

    if not tts_service:
        logger.bind(tag=TAG).error("无法获取 TTS 服务")
        return

    tts_service.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=context.sentence_id,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
    )
    tts_service.tts_one_sentence(context, ContentType.TEXT, content_detail=text)
    tts_service.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=context.sentence_id,
            sentence_type=SentenceType.LAST,
            content_type=ContentType.ACTION,
        )
    )
    context.dialogue.put(Message(role="assistant", content=text))
