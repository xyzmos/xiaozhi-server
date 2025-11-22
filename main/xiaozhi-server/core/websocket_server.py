import asyncio
import json

import websockets
from config.logger import setup_logging
from config.config_loader import get_config_from_api
from core.auth import AuthManager, AuthenticationError
from core.utils.modules_initialize import initialize_modules
from core.utils.util import check_vad_update, check_asr_update
from core.infrastructure.di.container import DIContainer
from core.infrastructure.event.event_bus import EventBus
from core.application.session_manager import SessionManager
from core.infrastructure.websocket.transport import WebSocketTransport
from core.infrastructure.websocket.message_router import WebSocketMessageRouter
from core.handle.event_handlers_registry import register_all_event_handlers
from core.domain.services.service_registry import register_domain_services

TAG = __name__


class WebSocketServer:
    def __init__(
        self,
        config: dict,
        container: DIContainer,
        event_bus: EventBus
    ):
        self.config = config
        self.logger = setup_logging()
        self.config_lock = asyncio.Lock()

        # 依赖注入容器和事件总线
        self.container = container
        self.event_bus = event_bus

        modules = initialize_modules(
            self.logger,
            self.config,
            "VAD" in self.config["selected_module"],
            "ASR" in self.config["selected_module"],
            "LLM" in self.config["selected_module"],
            False,
            "Memory" in self.config["selected_module"],
            "Intent" in self.config["selected_module"],
        )
        self._vad = modules["vad"] if "vad" in modules else None
        self._asr = modules["asr"] if "asr" in modules else None
        self._llm = modules["llm"] if "llm" in modules else None
        self._intent = modules["intent"] if "intent" in modules else None
        self._memory = modules["memory"] if "memory" in modules else None

        # 注册全局单例服务到容器
        if self._vad:
            self.container.register_singleton('vad', self._vad)
        if self._asr:
            self.container.register_singleton('asr', self._asr)
        if self._llm:
            self.container.register_singleton('llm', self._llm)
        if self._intent:
            self.container.register_singleton('intent', self._intent)
        if self._memory:
            self.container.register_singleton('memory', self._memory)

        # 注册基础设施服务
        self.container.register_singleton('logger', self.logger)
        self.container.register_singleton('event_bus', self.event_bus)

        # 创建 WebSocket 传输层
        self.ws_transport = WebSocketTransport()
        self.container.register_singleton('websocket_transport', self.ws_transport)

        # 创建消息路由器
        self.message_router = WebSocketMessageRouter(
            event_bus=self.event_bus,
            container=self.container
        )

        # 创建会话管理器
        self.session_manager = SessionManager(
            container=self.container,
            event_bus=self.event_bus,
            common_config=self.config
        )

        # 注册所有领域服务（必须在事件处理器之前注册）
        self.domain_services = register_domain_services(self.container, self.event_bus)
        self.logger.bind(tag=TAG).info("领域服务已注册")

        # 注册所有事件处理器
        self.event_handlers = register_all_event_handlers(self.container, self.event_bus)
        self.logger.bind(tag=TAG).info("事件处理器已注册")

        auth_config = self.config["server"].get("auth", {})
        self.auth_enable = auth_config.get("enabled", False)
        # 设备白名单
        self.allowed_devices = set(auth_config.get("allowed_devices", []))
        secret_key = self.config["server"]["auth_key"]
        expire_seconds = auth_config.get("expire_seconds", None)
        self.auth = AuthManager(secret_key=secret_key, expire_seconds=expire_seconds)

    async def start(self):
        server_config = self.config["server"]
        host = server_config.get("ip", "0.0.0.0")
        port = int(server_config.get("port", 8000))

        async with websockets.serve(
            self._handle_connection, host, port, process_request=self._http_response
        ):
            await asyncio.Future()

    async def _handle_connection(self, websocket):
        """处理新连接 - 使用新的事件驱动架构"""
        session_id = None

        try:
            headers = dict(websocket.request.headers)
            if headers.get("device-id", None) is None:
                # 尝试从 URL 的查询参数中获取 device-id
                from urllib.parse import parse_qs, urlparse

                # 从 WebSocket 请求中获取路径
                request_path = websocket.request.path
                if not request_path:
                    self.logger.bind(tag=TAG).error("无法获取请求路径")
                    await websocket.close()
                    return
                parsed_url = urlparse(request_path)
                query_params = parse_qs(parsed_url.query)
                if "device-id" not in query_params:
                    await websocket.send("端口正常，如需测试连接，请使用test_page.html")
                    await websocket.close()
                    return
                else:
                    websocket.request.headers["device-id"] = query_params["device-id"][0]
                if "client-id" in query_params:
                    websocket.request.headers["client-id"] = query_params["client-id"][0]
                if "authorization" in query_params:
                    websocket.request.headers["authorization"] = query_params[
                        "authorization"
                    ][0]

            # 先认证，后建立连接
            try:
                await self._handle_auth(websocket)
            except AuthenticationError:
                await websocket.send("认证失败")
                await websocket.close()
                return

            # 创建会话
            headers = dict(websocket.request.headers)
            session_id = await self.session_manager.create_session(
                websocket, headers=headers
            )

            self.logger.bind(tag=TAG).info(f"会话 {session_id} 已创建")

            # 注册 WebSocket 连接到传输层
            self.ws_transport.register(session_id, websocket)

            # 路由消息到事件总线
            try:
                async for message in websocket:
                    await self.message_router.route_message(session_id, message)
            except websockets.ConnectionClosed:
                self.logger.bind(tag=TAG).info(f"会话 {session_id} 客户端断开连接")
            except Exception as e:
                self.logger.bind(tag=TAG).error(f"会话 {session_id} 处理消息时出错: {e}")

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"处理连接时出错: {e}")
        finally:
            # 清理会话
            if session_id:
                try:
                    await self.session_manager.destroy_session(session_id)
                    self.ws_transport.unregister(session_id)
                    self.logger.bind(tag=TAG).info(f"会话 {session_id} 已清理")
                except Exception as cleanup_error:
                    self.logger.bind(tag=TAG).error(
                        f"会话 {session_id} 清理时出错: {cleanup_error}"
                    )

            # 强制关闭 WebSocket 连接
            try:
                if hasattr(websocket, "closed") and not websocket.closed:
                    await websocket.close()
                elif hasattr(websocket, "state") and websocket.state.name != "CLOSED":
                    await websocket.close()
                else:
                    await websocket.close()
            except Exception as close_error:
                self.logger.bind(tag=TAG).error(
                    f"关闭 WebSocket 时出错: {close_error}"
                )

    async def _http_response(self, websocket, request_headers):
        # 检查是否为 WebSocket 升级请求
        if request_headers.headers.get("connection", "").lower() == "upgrade":
            # 如果是 WebSocket 请求，返回 None 允许握手继续
            return None
        else:
            # 如果是普通 HTTP 请求，返回 "server is running"
            return websocket.respond(200, "Server is running\n")

    async def update_config(self) -> bool:
        """更新服务器配置并重新初始化组件

        Returns:
            bool: 更新是否成功
        """
        try:
            async with self.config_lock:
                # 重新获取配置
                new_config = get_config_from_api(self.config)
                if new_config is None:
                    self.logger.bind(tag=TAG).error("获取新配置失败")
                    return False
                self.logger.bind(tag=TAG).info(f"获取新配置成功")
                # 检查 VAD 和 ASR 类型是否需要更新
                update_vad = check_vad_update(self.config, new_config)
                update_asr = check_asr_update(self.config, new_config)
                self.logger.bind(tag=TAG).info(
                    f"检查VAD和ASR类型是否需要更新: {update_vad} {update_asr}"
                )
                # 更新配置
                self.config = new_config
                # 重新初始化组件
                modules = initialize_modules(
                    self.logger,
                    new_config,
                    update_vad,
                    update_asr,
                    "LLM" in new_config["selected_module"],
                    False,
                    "Memory" in new_config["selected_module"],
                    "Intent" in new_config["selected_module"],
                )

                # 更新组件实例
                if "vad" in modules:
                    self._vad = modules["vad"]
                if "asr" in modules:
                    self._asr = modules["asr"]
                if "llm" in modules:
                    self._llm = modules["llm"]
                if "intent" in modules:
                    self._intent = modules["intent"]
                if "memory" in modules:
                    self._memory = modules["memory"]
                self.logger.bind(tag=TAG).info(f"更新配置任务执行完毕")
                return True
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"更新服务器配置失败: {str(e)}")
            return False

    async def _handle_auth(self, websocket):
        # 先认证，后建立连接
        if self.auth_enable:
            headers = dict(websocket.request.headers)
            device_id = headers.get("device-id", None)
            client_id = headers.get("client-id", None)
            if self.allowed_devices and device_id in self.allowed_devices:
                # 如果属于白名单内的设备，不校验token，直接放行
                return
            else:
                # 否则校验token
                token = headers.get("authorization", "")
                if token.startswith("Bearer "):
                    token = token[7:]  # 移除'Bearer '前缀
                else:
                    raise AuthenticationError("Missing or invalid Authorization header")
                # 进行认证
                auth_success = self.auth.verify_token(
                    token, client_id=client_id, username=device_id
                )
                if not auth_success:
                    raise AuthenticationError("Invalid token")
