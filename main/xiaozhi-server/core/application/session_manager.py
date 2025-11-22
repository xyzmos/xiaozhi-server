"""会话管理器 - 负责会话的生命周期管理"""

import asyncio
import copy
import time
import uuid
from typing import Any, Dict, Optional

from config.config_loader import get_private_config_from_api
from config.logger import setup_logging
from config.manage_api_client import DeviceBindException, DeviceNotFoundException
from core.application.context import SessionContext
from core.infrastructure.di.container import DIContainer
from core.infrastructure.di.lifecycle import LifecycleManager
from core.infrastructure.event.event_bus import EventBus
from core.infrastructure.event.event_types import (
    SessionCreatedEvent,
    SessionDestroyingEvent,
)
from core.utils.dialogue import Dialogue
from core.utils.prompt_manager import PromptManager
from core.utils.voiceprint_provider import VoiceprintProvider


class SessionManager:
    """会话管理器 - 管理会话的创建、销毁和生命周期"""

    def __init__(
        self, container: DIContainer, event_bus: EventBus, common_config: Dict[str, Any]
    ):
        self.container = container
        self.event_bus = event_bus
        self.common_config = common_config
        self.sessions: Dict[str, SessionContext] = {}
        self.logger = setup_logging()

    async def create_session(self, websocket, headers: Dict[str, str]) -> str:
        """创建新会话

        Args:
            websocket: WebSocket 连接
            headers: HTTP 头部信息

        Returns:
            会话ID
        """
        session_id = str(uuid.uuid4())

        # 提取客户端信息
        real_ip = headers.get("x-real-ip") or headers.get("x-forwarded-for")
        if real_ip:
            client_ip = real_ip.split(",")[0].strip()
        else:
            client_ip = websocket.remote_address[0]

        device_id = headers.get("device-id", None)
        client_id = headers.get("client-id", None)

        # 检查是否来自MQTT连接
        request_path = websocket.request.path
        conn_from_mqtt_gateway = request_path.endswith("?from=mqtt_gateway")

        self.logger.info(
            f"创建会话 {session_id} - 设备: {device_id}, IP: {client_ip}, "
            f"来自MQTT: {conn_from_mqtt_gateway}"
        )

        # 复制配置
        config = copy.deepcopy(self.common_config)

        # 获取差异化配置
        read_config_from_api = config.get("read_config_from_api", False)
        need_bind = False
        bind_code = None

        if read_config_from_api:
            try:
                private_config = await get_private_config_from_api(device_id)
                config.update(private_config)
                self.logger.info(f"会话 {session_id} 加载API配置成功")
            except DeviceNotFoundException as e:
                self.logger.warning(f"设备未找到: {e}")
                need_bind = True
            except DeviceBindException as e:
                self.logger.warning(f"设备未绑定: {e}")
                need_bind = True
                bind_code = e.bind_code
            except Exception as e:
                self.logger.error(f"加载API配置失败: {e}")

        # 创建生命周期管理器
        lifecycle = LifecycleManager(session_id=session_id)

        # 创建会话上下文
        context = SessionContext(
            session_id=session_id,
            device_id=device_id,
            client_id=client_id,
            client_ip=client_ip,
            _config=config,
            lifecycle=lifecycle,
            conn_from_mqtt_gateway=conn_from_mqtt_gateway,
            need_bind=need_bind,
            bind_code=bind_code,
            last_activity_time=time.time() * 1000,
        )

        # 设置欢迎消息
        context.welcome_msg = config.get("xiaozhi", {})
        context.welcome_msg["session_id"] = session_id

        # 创建 Dialogue
        context.dialogue = Dialogue()

        # 创建 PromptManager
        context.prompt_manager = PromptManager(config, self.logger)

        # 创建 VoiceprintProvider
        voiceprint_config = config.get("voiceprint", {})
        context.voiceprint_provider = VoiceprintProvider(voiceprint_config)

        # 设置意图类型
        intent_config = config.get("Intent", {})
        selected_intent = config.get("selected_module", {}).get("Intent", "")
        if selected_intent and selected_intent in intent_config:
            context.intent_type = intent_config[selected_intent].get("type", "nointent")
            if context.intent_type in ("function_call", "intent_llm"):
                context.load_function_plugin = True
        else:
            context.intent_type = "nointent"

        # 设置退出命令
        context.cmd_exit = config.get("exit_commands", [])

        # 注册会话上下文到容器
        self.container.register_session_context(session_id, context)

        # 设置 context 的 container 引用
        context.container = self.container
        context.headers = headers

        # 初始化工具处理器（如果需要）
        if context.load_function_plugin:
            from core.providers.tools.unified_tool_handler import UnifiedToolHandler

            func_handler = UnifiedToolHandler(self.container, session_id)
            context.func_handler = func_handler
            # 异步初始化工具处理器
            asyncio.create_task(func_handler._initialize())
            self.logger.debug(f"会话 {session_id} 工具处理器已创建")

        # 保存会话
        self.sessions[session_id] = context

        # 发布会话创建事件
        await self.event_bus.publish(
            SessionCreatedEvent(
                session_id=session_id,
                device_id=device_id,
                client_ip=client_ip,
                timestamp=time.time(),
            )
        )

        # 启动超时监控
        asyncio.create_task(self._monitor_timeout(session_id))

        return session_id

    async def destroy_session(self, session_id: str):
        """销毁会话

        Args:
            session_id: 会话ID
        """
        context = self.sessions.get(session_id)
        if not context:
            self.logger.warning(f"会话 {session_id} 不存在，无法销毁")
            return

        self.logger.info(f"销毁会话 {session_id}")

        # 发布会话销毁事件
        await self.event_bus.publish(
            SessionDestroyingEvent(
                session_id=session_id,
                timestamp=time.time(),
            )
        )

        # 停止生命周期管理器
        await context.lifecycle.stop()

        # 清理资源
        await self._cleanup_session_resources(session_id, context)

        # 从容器移除会话级服务
        self.container.cleanup_session(session_id)

        # 删除会话
        del self.sessions[session_id]

        self.logger.info(f"会话 {session_id} 已销毁")

    async def get_session(self, session_id: str) -> Optional[SessionContext]:
        """获取会话上下文

        Args:
            session_id: 会话ID

        Returns:
            会话上下文，如果不存在则返回 None
        """
        return self.sessions.get(session_id)

    async def _monitor_timeout(self, session_id: str):
        """监控会话超时

        Args:
            session_id: 会话ID
        """
        context = self.sessions.get(session_id)
        if not context:
            return

        timeout = context.get_timeout_seconds()

        while not context.lifecycle.is_stopped():
            await asyncio.sleep(10)

            # 检查会话是否还存在
            if session_id not in self.sessions:
                break

            # 检查超时
            idle_time = (time.time() * 1000 - context.last_activity_time) / 1000
            if idle_time > timeout:
                self.logger.info(
                    f"会话 {session_id} 超时 ({idle_time:.0f}秒)，准备关闭"
                )
                await self.destroy_session(session_id)
                break

    async def _cleanup_session_resources(
        self, session_id: str, context: SessionContext
    ):
        """清理会话资源

        Args:
            session_id: 会话ID
            context: 会话上下文
        """
        try:
            # 保存记忆（如果存在）
            if context.dialogue and hasattr(context, "dialogue"):
                try:
                    # 从容器获取 memory 服务
                    memory = self.container.resolve("memory", session_id=session_id)
                    if memory:
                        await memory.save_memory(context.dialogue.dialogue)
                        self.logger.info(f"会话 {session_id} 记忆已保存")
                except Exception as e:
                    self.logger.error(f"保存记忆失败 {session_id}: {e}")

            # 清理其他资源（TTS队列、ASR队列等）
            # 这些清理会通过事件总线的 SessionDestroyingEvent 触发

        except Exception as e:
            self.logger.error(f"清理会话资源失败 {session_id}: {e}")
