"""意图识别服务"""

import time
import uuid
import json
import asyncio
from typing import TYPE_CHECKING, Optional

from config.logger import setup_logging
from core.utils.dialogue import Message
from core.utils.util import remove_punctuation_and_length
from core.providers.tts.dto.dto import ContentType, SentenceType, TTSMessageDTO
from plugins_func.register import Action, ActionResponse
from core.infrastructure.event.event_types import IntentRecognizedEvent

if TYPE_CHECKING:
    from core.infrastructure.di.container import DIContainer
    from core.infrastructure.event.event_bus import EventBus
    from core.application.context import SessionContext


class IntentService:
    """意图识别服务"""

    def __init__(self, container: 'DIContainer', event_bus: 'EventBus'):
        self.container = container
        self.event_bus = event_bus
        self.logger = setup_logging()

    async def handle_user_intent(self, context: 'SessionContext', text: str) -> bool:
        """处理用户意图

        Returns:
            True 如果意图已被处理，False 如果需要继续常规对话
        """
        # 预处理输入文本，处理可能的 JSON 格式
        try:
            if text.strip().startswith('{') and text.strip().endswith('}'):
                parsed_data = json.loads(text)
                if isinstance(parsed_data, dict) and "content" in parsed_data:
                    text = parsed_data["content"]
                    context.current_speaker = parsed_data.get("speaker")
        except (json.JSONDecodeError, TypeError):
            pass

        # 检查是否有明确的退出命令
        _, filtered_text = remove_punctuation_and_length(text)
        if await self._check_direct_exit(context, filtered_text):
            return True

        # 检查是否是唤醒词
        if await self._check_wakeup_words(context, filtered_text):
            return True

        if context.intent_type == "function_call":
            # 使用支持 function calling 的聊天方法，不再进行意图分析
            return False

        # 使用 LLM 进行意图分析
        intent_result = await self._analyze_intent_with_llm(context, text)
        if not intent_result:
            return False

        # 会话开始时生成 sentence_id
        context.sentence_id = str(uuid.uuid4().hex)

        # 处理各种意图
        return await self._process_intent_result(context, intent_result, text)

    async def _check_direct_exit(self, context: 'SessionContext', text: str) -> bool:
        """检查是否有明确的退出命令"""
        _, text = remove_punctuation_and_length(text)
        cmd_exit = context.get_config('cmd_exit', [])

        for cmd in cmd_exit:
            if text == cmd:
                self.logger.info(f"识别到明确的退出命令: {text}")
                await self._send_stt_message(context, text)

                # 发布会话销毁事件
                from core.infrastructure.event.event_types import SessionDestroyingEvent
                await self.event_bus.publish(SessionDestroyingEvent(
                    session_id=context.session_id,
                    timestamp=time.time()
                ))
                return True

        return False

    async def _check_wakeup_words(self, context: 'SessionContext', text: str) -> bool:
        """检查是否是唤醒词"""
        wakeup_words = context.get_config('wakeup_words', [])

        for word in wakeup_words:
            if text == word or text.endswith(word):
                self.logger.info(f"识别到唤醒词: {text}")

                # 获取欢迎消息
                welcome_text = context.get_config('xiaozhi.name', '小智')
                greeting = context.get_config('greeting', f'你好，我是{welcome_text}')

                # 发送欢迎消息
                tts_orchestrator = self.container.resolve('tts_orchestrator')
                await tts_orchestrator.synthesize_one_sentence(context.session_id, greeting)

                return True

        return False

    async def _analyze_intent_with_llm(self, context: 'SessionContext', text: str) -> Optional[str]:
        """使用 LLM 分析用户意图"""
        intent_provider = self.container.resolve('intent')
        if not intent_provider:
            self.logger.warning("意图识别服务未初始化")
            return None

        dialogue = context.dialogue
        try:
            intent_result = await intent_provider.detect_intent(context, dialogue.dialogue, text)
            return intent_result
        except Exception as e:
            self.logger.error(f"意图识别失败: {str(e)}")

        return None

    async def _process_intent_result(self, context: 'SessionContext', intent_result: str, original_text: str) -> bool:
        """处理意图识别结果"""
        session_id = context.session_id

        try:
            # 尝试将结果解析为 JSON
            intent_data = json.loads(intent_result)

            # 检查是否有 function_call
            if "function_call" not in intent_data:
                return False

            function_name = intent_data["function_call"]["name"]
            self.logger.debug(f"检测到 function_call 格式的意图结果: {function_name}")

            if function_name == "continue_chat":
                return False

            # 发布意图识别事件
            await self.event_bus.publish(IntentRecognizedEvent(
                session_id=session_id,
                timestamp=time.time(),
                intent=function_name,
                entities=intent_data["function_call"].get("arguments", {}),
                confidence=1.0
            ))

            if function_name == "result_for_context":
                await self._handle_context_result(context, original_text)
                return True

            # 处理函数调用
            function_args = intent_data["function_call"].get("arguments", {})
            if function_args is None:
                function_args = {}
            if isinstance(function_args, dict):
                function_args = json.dumps(function_args)

            function_call_data = {
                "name": function_name,
                "id": str(uuid.uuid4().hex),
                "arguments": function_args,
            }

            await self._send_stt_message(context, original_text)
            context.client_abort = False

            # 执行函数调用
            await self._process_function_call(context, function_call_data, original_text)
            return True

        except json.JSONDecodeError as e:
            self.logger.error(f"处理意图结果时出错: {e}")
            return False

    async def _handle_context_result(self, context: 'SessionContext', original_text: str):
        """处理上下文结果意图"""
        await self._send_stt_message(context, original_text)
        context.client_abort = False

        context.dialogue.put(Message(role="user", content=original_text))

        from core.utils.current_time import get_current_time_info
        current_time, today_date, today_weekday, lunar_date = get_current_time_info()

        # 构建带上下文的基础提示
        context_prompt = f"""当前时间：{current_time}
今天日期：{today_date} ({today_weekday})
今天农历：{lunar_date}

请根据以上信息回答用户的问题：{original_text}"""

        intent_provider = self.container.resolve('intent')
        if intent_provider:
            response = intent_provider.replyResult(context_prompt, original_text)
            await self._speak_text(context, response)

    async def _process_function_call(self, context: 'SessionContext', function_call_data: dict, original_text: str):
        """处理函数调用"""
        context.dialogue.put(Message(role="user", content=original_text))

        func_handler = context.func_handler
        if not func_handler:
            self.logger.error("函数处理器未初始化")
            return

        try:
            result = await func_handler.handle_llm_function_call(context, function_call_data)
        except Exception as e:
            self.logger.error(f"工具调用失败: {e}")
            result = ActionResponse(
                action=Action.ERROR,
                result=str(e),
                response=str(e)
            )

        if not result:
            return

        function_name = function_call_data['name']

        if result.action == Action.RESPONSE:
            text = result.response
            if text:
                await self._speak_text(context, text)

        elif result.action == Action.REQLLM:
            text = result.result
            context.dialogue.put(Message(role="tool", content=text))

            intent_provider = self.container.resolve('intent')
            if intent_provider:
                llm_result = intent_provider.replyResult(text, original_text)
                if llm_result is None:
                    llm_result = text
                await self._speak_text(context, llm_result)

        elif result.action in [Action.NOTFOUND, Action.ERROR]:
            text = result.result
            if text:
                await self._speak_text(context, text)

    async def _speak_text(self, context: 'SessionContext', text: str):
        """播放文本"""
        tts_orchestrator = self.container.resolve('tts_orchestrator')
        await tts_orchestrator.synthesize_one_sentence(context.session_id, text)
        context.dialogue.put(Message(role="assistant", content=text))

    async def _send_stt_message(self, context: 'SessionContext', text: str):
        """发送 STT 消息到客户端"""
        ws_transport = self.container.resolve('websocket_transport')
        if ws_transport:
            await ws_transport.send_json(context.session_id, {
                "type": "stt",
                "text": text
            })


def register_intent_service(container: 'DIContainer', event_bus: 'EventBus'):
    """注册意图服务"""
    service = IntentService(container, event_bus)
    return service
