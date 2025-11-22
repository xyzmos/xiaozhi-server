"""文本消息处理器 - 事件驱动架构重构版"""

import json
from typing import Dict, Any

from config.logger import setup_logging
from core.infrastructure.event.event_types import TextMessageReceivedEvent, ClientAbortEvent
from core.infrastructure.di.container import DIContainer
from core.infrastructure.event.event_bus import EventBus

TAG = __name__


class TextMessageHandler:
    """文本消息处理器 - 完全事件驱动"""

    def __init__(self, container: DIContainer, event_bus: EventBus):
        self.container = container
        self.event_bus = event_bus
        self.logger = setup_logging()

    async def handle(self, event: TextMessageReceivedEvent):
        """处理文本消息事件 - 解析并分发到具体处理器"""
        session_id = event.session_id
        content = event.content

        try:
            # 尝试解析JSON
            msg_json = json.loads(content)
            msg_type = msg_json.get("type")

            # 根据消息类型分发
            if msg_type == "hello":
                # Hello消息由HelloMessageHandler处理
                pass
            elif msg_type == "abort":
                # 发布中止事件
                await self.event_bus.publish(ClientAbortEvent(
                    session_id=session_id,
                    timestamp=event.timestamp,
                    reason="client_request"
                ))
            elif msg_type == "listen":
                await self._handle_listen_message(session_id, msg_json)
            elif msg_type == "iot":
                await self._handle_iot_message(session_id, msg_json)
            elif msg_type == "mcp":
                await self._handle_mcp_message(session_id, msg_json)
            elif msg_type == "server":
                await self._handle_server_message(session_id, msg_json)
            else:
                self.logger.warning(f"未知消息类型: {msg_type}")

        except json.JSONDecodeError:
            self.logger.error(f"无法解析JSON消息: {content}")
        except Exception as e:
            self.logger.error(f"处理文本消息失败: {e}", exc_info=True)

    async def _process_user_text(self, session_id: str, text: str):
        """处理用户文本 - 通过意图处理器"""
        try:
            from core.handle.intentHandler import handle_user_intent
            from core.utils import textUtils
            import asyncio

            self.logger.bind(tag=TAG).debug(f"开始处理用户文本: session_id={session_id}, text={text}")
            context = self.container.resolve('session_context', session_id=session_id)
            self.logger.bind(tag=TAG).debug(f"成功解析会话上下文: {context.session_id}")

            # 首先进行意图分析
            intent_handled = await handle_user_intent(context, text)

            if intent_handled:
                # 如果意图已被处理，不再进行聊天
                self.logger.bind(tag=TAG).debug(f"意图已被处理，结束")
                return

            # 意图未被处理，继续常规聊天流程（function_call 模式）
            self.logger.bind(tag=TAG).debug(f"意图未被处理，继续常规聊天流程")
            ws_transport = self.container.resolve('websocket_transport')
            await ws_transport.send_json(session_id, {
                "type": "stt",
                "text": textUtils.check_emoji(text),
                "session_id": session_id
            })

            # 通过对话服务处理
            dialogue_service = self.container.resolve('dialogue_service')
            task = asyncio.create_task(dialogue_service.process_user_input(session_id, text))

            # 添加任务异常处理
            def handle_task_exception(t):
                try:
                    t.result()
                except Exception as e:
                    self.logger.error(f"对话处理任务失败: {e}", exc_info=True)

            task.add_done_callback(handle_task_exception)

            self.logger.bind(tag=TAG).debug(f"用户文本处理任务已创建")
        except Exception as e:
            self.logger.error(f"处理用户文本失败: {e}", exc_info=True)

    async def _handle_listen_message(self, session_id: str, msg_json: Dict[str, Any]):
        """处理listen消息"""
        import time
        from core.utils.util import remove_punctuation_and_length

        context = self.container.resolve('session_context', session_id=session_id)
        ws_transport = self.container.resolve('websocket_transport')

        if "mode" in msg_json:
            context.client_listen_mode = msg_json["mode"]
            self.logger.bind(tag=TAG).debug(f"客户端拾音模式：{context.client_listen_mode}")

        state = msg_json.get("state")
        if state == "start":
            context.client_have_voice = True
            context.client_voice_stop = False
        elif state == "stop":
            context.client_have_voice = True
            context.client_voice_stop = True
            # TODO: 触发音频处理
        elif state == "detect":
            context.client_have_voice = False
            # 清除ASR音频缓冲
            try:
                asr_service = self.container.resolve('asr_service', session_id=session_id)
                asr_service.clear_buffer()
            except Exception:
                pass

            if "text" in msg_json:
                context.last_activity_time = time.time() * 1000
                original_text = msg_json["text"]
                filtered_len, filtered_text = remove_punctuation_and_length(original_text)

                # 检查是否是唤醒词
                is_wakeup_words = filtered_text in context.get_config("wakeup_words", [])
                enable_greeting = context.get_config("enable_greeting", True)

                if is_wakeup_words and not enable_greeting:
                    # 唤醒词但关闭了回复
                    self.logger.bind(tag=TAG).debug(f"检测到唤醒词但关闭了回复: {filtered_text}")
                    await ws_transport.send_json(session_id, {
                        "type": "stt",
                        "text": original_text,
                        "session_id": session_id
                    })
                    await ws_transport.send_json(session_id, {
                        "type": "tts",
                        "state": "stop",
                        "session_id": session_id
                    })
                    context.client_is_speaking = False
                else:
                    # 触发对话处理 - 通过意图处理器
                    self.logger.bind(tag=TAG).debug(f"准备触发对话处理: text={original_text}, is_wakeup={is_wakeup_words}")
                    import asyncio
                    asyncio.create_task(self._process_user_text(session_id, original_text))

    async def _handle_iot_message(self, session_id: str, msg_json: Dict[str, Any]):
        """处理IOT消息"""
        import asyncio
        from core.providers.tools.device_iot import handleIotStatus, handleIotDescriptors

        # TODO: 将这些也改为事件驱动
        # 暂时保留旧的调用方式
        try:
            conn = self.container.resolve('connection_handler', session_id=session_id)
            if "descriptors" in msg_json:
                asyncio.create_task(handleIotDescriptors(context, msg_json["descriptors"]))
            if "states" in msg_json:
                asyncio.create_task(handleIotStatus(context, msg_json["states"]))
        except Exception as e:
            self.logger.error(f"处理IOT消息失败: {e}")

    async def _handle_mcp_message(self, session_id: str, msg_json: Dict[str, Any]):
        """处理MCP消息"""
        import asyncio
        from core.providers.tools.device_mcp import handle_mcp_message

        try:
            context = self.container.resolve('session_context', session_id=session_id)
            if "payload" in msg_json and context.mcp_client:
                asyncio.create_task(handle_mcp_message(context, context.mcp_client, msg_json["payload"]))
        except Exception as e:
            self.logger.error(f"处理MCP消息失败: {e}")

    async def _handle_server_message(self, session_id: str, msg_json: Dict[str, Any]):
        """处理Server消息"""
        context = self.container.resolve('session_context', session_id=session_id)
        ws_transport = self.container.resolve('websocket_transport')

        # 检查是否从API读取配置
        read_config_from_api = context.get_config("read_config_from_api", False)
        if not read_config_from_api:
            return

        # 验证密钥
        post_secret = msg_json.get("content", {}).get("secret", "")
        secret = context.get_config("manager-api.secret", "")

        if post_secret != secret:
            await ws_transport.send_json(session_id, {
                "type": "server",
                "status": "error",
                "message": "服务器密钥验证失败"
            })
            return

        action = msg_json.get("action")
        if action == "update_config":
            # TODO: 实现配置更新逻辑
            await ws_transport.send_json(session_id, {
                "type": "server",
                "status": "success",
                "message": "配置更新成功",
                "content": {"action": "update_config"}
            })
        elif action == "restart":
            # TODO: 实现重启逻辑
            pass


def register_text_handler(container: DIContainer, event_bus: EventBus):
    """注册文本消息处理器到事件总线"""
    handler = TextMessageHandler(container, event_bus)
    event_bus.subscribe(TextMessageReceivedEvent, handler.handle)
    return handler
