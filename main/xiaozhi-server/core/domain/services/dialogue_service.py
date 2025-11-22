"""对话管理服务 - 整合 LLM 交互逻辑"""

import time
import uuid
import asyncio
import json
from typing import TYPE_CHECKING, List, Optional, Any

from config.logger import setup_logging
from core.utils.dialogue import Message
from core.providers.tts.dto.dto import ContentType, SentenceType, TTSMessageDTO
from core.infrastructure.event.event_types import (
    ASRTranscriptEvent,
    LLMResponseEvent,
    TTSRequestEvent,
    ToolCallRequestEvent,
    ToolCallResponseEvent,
)
from plugins_func.register import Action, ActionResponse

if TYPE_CHECKING:
    from core.infrastructure.di.container import DIContainer
    from core.infrastructure.event.event_bus import EventBus
    from core.application.context import SessionContext


class DialogueService:
    """对话服务 - 替代 ConnectionHandler.chat()"""

    def __init__(self, container: 'DIContainer', event_bus: 'EventBus'):
        self.container = container
        self.event_bus = event_bus
        self.logger = setup_logging()

    async def handle_asr_transcript(self, event: ASRTranscriptEvent):
        """处理 ASR 转录结果事件"""
        if not event.is_final:
            return

        session_id = event.session_id
        text = event.text

        # 获取上下文
        context: 'SessionContext' = self.container.resolve('session_context', session_id=session_id)
        if not context:
            self.logger.error(f"会话 {session_id} 的上下文不存在")
            return

        # 检查是否需要绑定设备
        if context.need_bind:
            await self._check_bind_device(context)
            return

        # 检查输出限制
        if await self._check_output_limit(context):
            return

        # 如果正在说话且不是 manual 模式，中止当前播放
        if context.client_is_speaking and context.client_listen_mode != "manual":
            from core.infrastructure.event.event_types import ClientAbortEvent
            await self.event_bus.publish(ClientAbortEvent(
                session_id=session_id,
                timestamp=time.time(),
                reason="user_interrupt"
            ))

        # 调用意图服务
        intent_service = self.container.resolve('intent_service')
        intent_handled = await intent_service.handle_user_intent(context, text)

        if intent_handled:
            return

        # 意图未被处理，继续常规聊天流程
        await self._send_stt_message(context, text)
        await self.process_user_input(session_id, text)

    async def process_user_input(self, session_id: str, text: str, depth: int = 0):
        """处理用户输入"""
        context: 'SessionContext' = self.container.resolve('session_context', session_id=session_id)
        if not context:
            self.logger.error(f"会话 {session_id} 的上下文不存在")
            return

        dialogue = context.dialogue
        llm = self.container.resolve('llm')

        # 首次调用时初始化
        if depth == 0:
            context.llm_finish_task = False
            context.sentence_id = str(uuid.uuid4().hex)
            dialogue.put(Message(role="user", content=text))

            # 发送 TTS 开始消息
            tts_orchestrator = self.container.resolve('tts_orchestrator')
            await tts_orchestrator.add_first_message(session_id)

        # 检查最大深度
        MAX_DEPTH = 5
        force_final_answer = depth >= MAX_DEPTH

        # 获取记忆
        memory_str = None
        memory_service = self.container.resolve('memory', session_id=session_id)
        if memory_service:
            try:
                memory_str = await memory_service.query_memory(text)
            except Exception as e:
                self.logger.error(f"查询记忆失败: {e}")

        # 获取函数列表
        functions = None
        if context.intent_type == "function_call" and not force_final_answer:
            if context.func_handler:
                functions = context.func_handler.get_functions()

        # 获取声纹配置
        voiceprint_config = None
        if context.voiceprint_provider and context.voiceprint_provider.enabled:
            # 构造声纹配置字典（用于 LLM 对话增强）
            voiceprint_config = {
                "speakers": context.voiceprint_provider.speakers
            }

        # 调用 LLM
        response_chunks = []
        tool_calls = []

        try:
            self.logger.debug(f"准备调用 LLM: functions={functions is not None}")

            if functions:
                llm_responses = llm.response_with_functions(
                    session_id,
                    dialogue.get_llm_dialogue_with_memory(memory_str, voiceprint_config),
                    functions=functions
                )
            else:
                llm_responses = llm.response(
                    session_id,
                    dialogue.get_llm_dialogue_with_memory(memory_str, voiceprint_config)
                )

            self.logger.debug(f"LLM 已返回响应生成器，开始处理流式响应")

            # 处理流式响应
            tts_orchestrator = self.container.resolve('tts_orchestrator')

            chunk_count = 0
            for chunk in llm_responses:
                chunk_count += 1
                if chunk_count == 1:
                    self.logger.debug(f"收到第一个 LLM 响应块")

                if context.client_abort:
                    break

                content, tools = self._parse_chunk(chunk, functions)

                if chunk_count <= 3:
                    self.logger.debug(f"块 {chunk_count}: content={content}, tools={tools}")

                if tools:
                    tool_calls.extend(tools)

                if content:
                    response_chunks.append(content)
                    # 发送到 TTS
                    await tts_orchestrator.add_text_message(session_id, content)

            self.logger.debug(f"LLM 流式响应处理完成，共 {chunk_count} 个块，响应文本长度: {len(''.join(response_chunks))}")

        except Exception as e:
            self.logger.error(f"LLM 处理失败: {e}", exc_info=True)
            return

        # 处理函数调用
        if tool_calls and not context.client_abort:
            self.logger.debug(f"检测到工具调用，共 {len(tool_calls)} 个")
            await self._handle_tool_calls(context, tool_calls, text, depth)
        else:
            # 保存对话
            if response_chunks:
                full_response = "".join(response_chunks)
                dialogue.put(Message(role="assistant", content=full_response))
                context.tts_message_text = full_response

        # 结束标记
        if depth == 0:
            tts_orchestrator = self.container.resolve('tts_orchestrator')
            await tts_orchestrator.add_last_message(session_id)
            context.llm_finish_task = True

    def _parse_chunk(self, chunk: Any, functions: Optional[List]) -> tuple:
        """解析 LLM 响应块"""
        content = None
        tools = []

        # 如果有函数调用，response_with_functions 返回的是 (content, tools_call) 元组
        if functions and isinstance(chunk, tuple) and len(chunk) == 2:
            content, tools = chunk
            # 兼容字典格式
            if isinstance(chunk, dict) and "content" in chunk:
                content = chunk["content"]
                tools = None
        elif isinstance(chunk, str):
            content = chunk
        elif hasattr(chunk, 'content'):
            content = chunk.content
        elif hasattr(chunk, 'tool_calls') and chunk.tool_calls:
            tools = chunk.tool_calls

        return content, tools if tools else []

    async def _handle_tool_calls(self, context: 'SessionContext', tool_calls: List, original_text: str, depth: int):
        """处理工具调用"""
        session_id = context.session_id

        for tool_call in tool_calls:
            if context.client_abort:
                break

            # 获取工具调用信息 - 兼容字典和对象两种格式
            if isinstance(tool_call, dict):
                tool_name = tool_call.get('name', '')
                tool_args = tool_call.get('arguments', '{}')
                tool_id = tool_call.get('id', str(uuid.uuid4().hex))
            else:
                # 对象格式（如 ChoiceDeltaToolCall）
                tool_id = getattr(tool_call, 'id', str(uuid.uuid4().hex))
                func = getattr(tool_call, 'function', None)
                if func:
                    tool_name = getattr(func, 'name', '')
                    tool_args = getattr(func, 'arguments', '{}')
                else:
                    tool_name = ''
                    tool_args = '{}'

            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except json.JSONDecodeError:
                    tool_args = {}

            # 发布工具调用事件
            await self.event_bus.publish(ToolCallRequestEvent(
                session_id=session_id,
                timestamp=time.time(),
                tool_name=tool_name,
                parameters=tool_args,
                tool_call_id=tool_id
            ))

            # 执行工具调用
            if context.func_handler:
                try:
                    result = await context.func_handler.handle_llm_function_call(
                        {
                            'name': tool_name,
                            'id': tool_id,
                            'arguments': json.dumps(tool_args) if isinstance(tool_args, dict) else tool_args
                        }
                    )

                    # 处理结果
                    if result:
                        await self._process_tool_result(context, result, tool_id, original_text, depth)

                except Exception as e:
                    self.logger.error(f"工具调用失败: {e}", exc_info=True)
                    result = ActionResponse(
                        action=Action.ERROR,
                        result=str(e),
                        response=str(e)
                    )
                    await self._process_tool_result(context, result, tool_id, original_text, depth)

    async def _process_tool_result(self, context: 'SessionContext', result: ActionResponse, tool_id: str, original_text: str, depth: int):
        """处理工具调用结果"""
        session_id = context.session_id
        tts_orchestrator = self.container.resolve('tts_orchestrator')

        if result.action == Action.RESPONSE:
            # 直接回复
            if result.response:
                await tts_orchestrator.synthesize_one_sentence(session_id, result.response)
                context.dialogue.put(Message(role="assistant", content=result.response))

        elif result.action == Action.REQLLM:
            # 调用函数后再请求 LLM 生成回复
            text = result.result
            context.dialogue.put(Message(role="tool", content=text, tool_call_id=tool_id))
            # 递归调用
            await self.process_user_input(session_id, original_text, depth + 1)

        elif result.action in [Action.NOTFOUND, Action.ERROR]:
            if result.result:
                await tts_orchestrator.synthesize_one_sentence(session_id, result.result)

        elif result.action == Action.NONE:
            # 无需处理
            pass

    async def _send_stt_message(self, context: 'SessionContext', text: str):
        """发送 STT 消息到客户端"""
        ws_transport = self.container.resolve('websocket_transport')
        if ws_transport:
            await ws_transport.send_json(context.session_id, {
                "type": "stt",
                "text": text
            })

    async def _check_bind_device(self, context: 'SessionContext'):
        """检查设备绑定"""
        tts_orchestrator = self.container.resolve('tts_orchestrator')
        session_id = context.session_id

        if context.bind_code:
            if len(context.bind_code) != 6:
                self.logger.error(f"无效的绑定码格式: {context.bind_code}")
                await tts_orchestrator.synthesize_one_sentence(
                    session_id,
                    "绑定码格式错误，请检查配置。"
                )
                return

            text = f"请登录控制面板，输入{context.bind_code}，绑定设备。"
            await self._send_stt_message(context, text)

            # 播放绑定码音频
            from core.utils.util import audio_to_data
            music_path = "config/assets/bind_code.wav"
            opus_packets = audio_to_data(music_path)

            tts = self.container.resolve('tts', session_id=session_id)
            if tts:
                tts.tts_audio_queue.put((SentenceType.FIRST, opus_packets, text))

                # 逐个播放数字
                for digit in context.bind_code:
                    try:
                        num_path = f"config/assets/bind_code/{digit}.wav"
                        num_packets = audio_to_data(num_path)
                        tts.tts_audio_queue.put((SentenceType.MIDDLE, num_packets, None))
                    except Exception as e:
                        self.logger.error(f"播放数字音频失败: {e}")

                tts.tts_audio_queue.put((SentenceType.LAST, [], None))
        else:
            # 播放未绑定提示
            context.client_abort = False
            text = "没有找到该设备的版本信息，请正确配置 OTA地址，然后重新编译固件。"
            await self._send_stt_message(context, text)

            from core.utils.util import audio_to_data
            music_path = "config/assets/bind_not_found.wav"
            opus_packets = audio_to_data(music_path)

            tts = self.container.resolve('tts', session_id=session_id)
            if tts:
                tts.tts_audio_queue.put((SentenceType.LAST, opus_packets, text))

    async def _check_output_limit(self, context: 'SessionContext') -> bool:
        """检查输出限制"""
        max_output_size = context.get_config('max_output_size', 0)
        if max_output_size <= 0:
            return False

        from core.utils.output_counter import check_device_output_limit
        device_id = context.device_id

        if check_device_output_limit(device_id, max_output_size):
            # 播放超出最大输出字数的提示
            context.client_abort = False
            text = "不好意思，我现在有点事情要忙，明天这个时候我们再聊，约好了哦！明天不见不散，拜拜！"
            await self._send_stt_message(context, text)

            from core.utils.util import audio_to_data
            file_path = "config/assets/max_output_size.wav"
            opus_packets = audio_to_data(file_path)

            tts = self.container.resolve('tts', session_id=context.session_id)
            if tts:
                tts.tts_audio_queue.put((SentenceType.LAST, opus_packets, text))

            context.close_after_chat = True
            return True

        return False


def register_dialogue_service(container: 'DIContainer', event_bus: 'EventBus'):
    """注册对话服务到事件总线"""
    service = DialogueService(container, event_bus)
    event_bus.subscribe(ASRTranscriptEvent, service.handle_asr_transcript)
    return service
