# 小智 ESP32 服务器架构重构任务清单

> **重构目标**：事件驱动 + 依赖注入 + 生命周期管理
> **重构策略**：大刀阔斧式完全重构，不考虑渐进性
> **重构原则**：解耦、可测试、可扩展、清晰的职责边界

## 📊 重构统计

- **新增文件**: 45 个
- **修改文件**: 28 个
- **删除文件**: 1 个
- **保留文件**: 120+ 个

---

## 🎯 核心架构变更

### 架构层次划分

```
应用层 (Application)      - 业务编排、会话管理
  ↓
领域层 (Domain)           - 核心业务逻辑、领域服务
  ↓
基础设施层 (Infrastructure) - 事件总线、DI容器、传输层
  ↓
提供者层 (Providers)       - ASR/TTS/VAD/LLM 具体实现
```

### 核心设计模式

1. **依赖注入 (DI)**: 所有服务通过容器解析，消除硬依赖
2. **事件驱动**: 模块间通过事件总线通信，完全解耦
3. **生命周期管理**: 每个会话独立的生命周期管理器
4. **服务定位器**: 插件通过 PluginContext 获取服务

---

## 📁 完整文件树（重构前+重构后）

### 根目录文件

```
xiaozhi-esp32-server/main/xiaozhi-server/
│
├── app.py                                          [🔄 修改]
│   ├── 移除: 直接创建 ConnectionHandler 的逻辑
│   ├── 新增: 初始化 DIContainer 和 EventBus
│   ├── 新增: 注册所有服务到容器
│   └── 修改: WebSocketServer 初始化方式
│
├── REFACTOR_TASK.md                                [✨ 新增 - 本文件]
│
└── README.md                                       [📦 保留]
```

---

## 🏗️ core/ 核心目录

### 1. 顶层核心文件

```
core/
│
├── connection.py                                   [🗑️ 删除]
│   └── 原因: ConnectionHandler 职责过重，违反单一职责原则
│        - 包含 WebSocket 处理、VAD/ASR/TTS 管理、配置管理、生命周期管理
│        - 与所有模块强耦合，难以测试和扩展
│        - 功能被拆分到以下模块：
│          • application/session_manager.py (会话管理)
│          • application/context.py (会话上下文)
│          • infrastructure/websocket/transport.py (传输层)
│          • domain/services/* (业务服务)
│
├── auth.py                                         [📦 保留]
│   └── 认证模块保持不变
│
├── websocket_server.py                             [🔄 修改]
│   ├── 移除: 直接创建 ConnectionHandler 实例
│   ├── 新增: 注入 DIContainer 和 EventBus
│   ├── 修改: _handle_connection 方法
│   │   └── 实现细节:
│   │       1. 接收新连接后，通过 SessionManager 创建会话
│   │       2. 将 WebSocket 注册到 WebSocketTransport
│   │       3. 启动 MessageRouter 路由消息
│   │       4. 监听会话关闭事件
│   └── 示例代码:
│       ```python
│       async def _handle_connection(self, websocket):
│           # 认证
│           await self._handle_auth(websocket)
│
│           # 创建会话
│           session_id = await self.session_manager.create_session(
│               websocket, headers=dict(websocket.request.headers)
│           )
│
│           # 注册 WebSocket 连接
│           self.ws_transport.register(session_id, websocket)
│
│           # 路由消息
│           try:
│               async for message in websocket:
│                   await self.message_router.route_message(session_id, message)
│           except websockets.ConnectionClosed:
│               pass
│           finally:
│               # 清理会话
│               await self.session_manager.destroy_session(session_id)
│               self.ws_transport.unregister(session_id)
│       ```
│
├── http_server.py                                  [📦 保留]
│   └── HTTP服务器保持不变
```

---

### 2. core/application/ 应用层（新增）

```
core/application/
│
├── __init__.py                                     [✨ 新增]
│   └── 导出 SessionManager, SessionContext
│
├── session_manager.py                              [✨ 新增]
│   ├── 功能: 会话生命周期管理
│   ├── 职责:
│   │   • 创建/销毁会话
│   │   • 维护会话列表
│   │   • 会话状态监控
│   │   • 超时检测
│   └── 实现细节:
│       ```python
│       class SessionManager:
│           def __init__(self, container: DIContainer, event_bus: EventBus):
│               self.container = container
│               self.event_bus = event_bus
│               self.sessions: Dict[str, SessionContext] = {}
│               self.logger = setup_logging()
│
│           async def create_session(self, websocket, headers: Dict) -> str:
│               """创建新会话"""
│               session_id = str(uuid.uuid4())
│
│               # 从容器解析会话上下文
│               context = self.container.resolve(
│                   'session_context',
│                   session_id=session_id,
│                   headers=headers
│               )
│
│               self.sessions[session_id] = context
│
│               # 发布会话创建事件
│               await self.event_bus.publish(SessionCreatedEvent(
│                   session_id=session_id,
│                   device_id=context.device_id,
│                   client_ip=context.client_ip
│               ))
│
│               # 启动超时检测
│               asyncio.create_task(self._monitor_timeout(session_id))
│
│               return session_id
│
│           async def destroy_session(self, session_id: str):
│               """销毁会话"""
│               context = self.sessions.get(session_id)
│               if not context:
│                   return
│
│               # 发布会话销毁事件
│               await self.event_bus.publish(SessionDestroyingEvent(
│                   session_id=session_id
│               ))
│
│               # 停止生命周期管理器
│               await context.lifecycle.stop()
│
│               # 清理资源
│               await self._cleanup_session_resources(session_id)
│
│               # 从容器移除会话级服务
│               self.container.cleanup_session(session_id)
│
│               del self.sessions[session_id]
│
│           async def _monitor_timeout(self, session_id: str):
│               """监控会话超时"""
│               context = self.sessions.get(session_id)
│               if not context:
│                   return
│
│               timeout = context.get_config('close_connection_no_voice_time', 120)
│
│               while not context.lifecycle.is_stopped():
│                   await asyncio.sleep(10)
│
│                   if time.time() - context.last_activity_time > timeout:
│                       self.logger.info(f"会话 {session_id} 超时，准备关闭")
│                       await self.destroy_session(session_id)
│                       break
│
│           async def _cleanup_session_resources(self, session_id: str):
│               """清理会话资源"""
│               # 清理 TTS 队列
│               tts_service = self.container.resolve(
│                   'tts_orchestrator',
│                   session_id=session_id
│               )
│               await tts_service.cleanup()
│
│               # 清理 ASR 队列
│               asr_service = self.container.resolve(
│                   'asr_service',
│                   session_id=session_id
│               )
│               await asr_service.cleanup()
│
│               # 保存记忆
│               memory_service = self.container.resolve(
│                   'memory_service',
│                   session_id=session_id
│               )
│               if memory_service:
│                   await memory_service.save_memory()
│       ```
│
└── context.py                                      [✨ 新增]
    ├── 功能: 会话上下文（替代 ConnectionHandler 的配置部分）
    ├── 职责:
    │   • 存储会话配置
    │   • 存储会话状态
    │   • 提供配置访问接口
    └── 实现细节:
        ```python
        @dataclass
        class SessionContext:
            """会话上下文 - 替代 ConnectionHandler 的状态管理部分"""

            # 会话标识
            session_id: str
            device_id: Optional[str]
            client_id: Optional[str]
            client_ip: str

            # 配置
            _config: Dict[str, Any]

            # 生命周期管理器
            lifecycle: 'LifecycleManager'

            # 会话状态
            audio_format: str = "opus"
            features: Optional[Dict] = None
            welcome_msg: Dict = field(default_factory=dict)

            # 客户端状态
            client_abort: bool = False
            client_is_speaking: bool = False
            client_listen_mode: str = "auto"
            just_woken_up: bool = False

            # VAD 状态
            client_have_voice: bool = False
            client_voice_stop: bool = False
            last_is_voice: bool = False
            last_activity_time: float = 0.0

            # LLM 状态
            llm_finish_task: bool = True
            sentence_id: Optional[str] = None
            tts_message_text: str = ""

            # 其他状态
            need_bind: bool = False
            bind_code: Optional[str] = None
            close_after_chat: bool = False
            current_speaker: Optional[str] = None
            conn_from_mqtt_gateway: bool = False

            # MCP 客户端
            mcp_client: Optional[Any] = None

            def get_config(self, key: str, default=None) -> Any:
                """获取配置项"""
                keys = key.split('.')
                value = self._config
                for k in keys:
                    if isinstance(value, dict):
                        value = value.get(k, default)
                    else:
                        return default
                return value if value is not None else default

            def update_config(self, key: str, value: Any):
                """更新配置项"""
                keys = key.split('.')
                config = self._config
                for k in keys[:-1]:
                    if k not in config:
                        config[k] = {}
                    config = config[k]
                config[keys[-1]] = value

            def update_activity_time(self):
                """更新活动时间"""
                self.last_activity_time = time.time()
        ```
```

---

### 3. core/infrastructure/ 基础设施层（新增）

```
core/infrastructure/
│
├── __init__.py                                     [✨ 新增]
│   └── 导出核心基础设施组件
│
├── websocket/                                      [✨ 新增目录]
│   ├── __init__.py                                 [✨ 新增]
│   │
│   ├── transport.py                                [✨ 新增]
│   │   ├── 功能: WebSocket 传输层（解耦自 ConnectionHandler）
│   │   ├── 职责:
│   │   │   • 管理 WebSocket 连接
│   │   │   • 发送数据到客户端
│   │   │   • 连接注册/注销
│   │   └── 实现细节:
│   │       ```python
│   │       class WebSocketTransport:
│   │           """WebSocket 传输层 - 负责底层数据发送"""
│   │
│   │           def __init__(self):
│   │               self._connections: Dict[str, websockets.WebSocketServerProtocol] = {}
│   │               self._send_locks: Dict[str, asyncio.Lock] = {}
│   │               self.logger = setup_logging()
│   │
│   │           def register(self, session_id: str, websocket):
│   │               """注册会话的WebSocket连接"""
│   │               self._connections[session_id] = websocket
│   │               self._send_locks[session_id] = asyncio.Lock()
│   │               self.logger.debug(f"WebSocket已注册: {session_id}")
│   │
│   │           async def send(self, session_id: str, data: Union[str, bytes]):
│   │               """发送数据到指定会话"""
│   │               ws = self._connections.get(session_id)
│   │               if not ws:
│   │                   raise ValueError(f"会话 {session_id} 的WebSocket不存在")
│   │
│   │               # 使用锁保证线程安全
│   │               async with self._send_locks[session_id]:
│   │                   try:
│   │                       await ws.send(data)
│   │                   except Exception as e:
│   │                       self.logger.error(f"发送数据失败 {session_id}: {e}")
│   │                       raise
│   │
│   │           async def send_json(self, session_id: str, data: Dict):
│   │               """发送JSON数据"""
│   │               await self.send(session_id, json.dumps(data))
│   │
│   │           def unregister(self, session_id: str):
│   │               """注销会话连接"""
│   │               self._connections.pop(session_id, None)
│   │               self._send_locks.pop(session_id, None)
│   │               self.logger.debug(f"WebSocket已注销: {session_id}")
│   │
│   │           def is_connected(self, session_id: str) -> bool:
│   │               """检查会话是否连接"""
│   │               ws = self._connections.get(session_id)
│   │               if not ws:
│   │                   return False
│   │               return not ws.closed if hasattr(ws, 'closed') else True
│   │       ```
│   │
│   └── message_router.py                           [✨ 新增]
│       ├── 功能: 消息路由器（解耦自 ConnectionHandler._route_message）
│       ├── 职责:
│       │   • 路由不同类型的消息
│       │   • 发布对应的事件
│       │   • 处理MQTT网关消息
│       └── 实现细节:
│           ```python
│           class WebSocketMessageRouter:
│               """WebSocket 消息路由器 - 将消息转换为事件"""
│
│               def __init__(self, event_bus: EventBus, container: DIContainer):
│                   self.event_bus = event_bus
│                   self.container = container
│                   self.logger = setup_logging()
│
│               async def route_message(self, session_id: str, message: Union[str, bytes]):
│                   """路由消息到事件总线"""
│                   # 获取会话上下文
│                   context = self.container.resolve('session_context', session_id=session_id)
│                   context.update_activity_time()
│
│                   if isinstance(message, str):
│                       # 文本消息 -> TextMessageReceivedEvent
│                       await self._route_text_message(session_id, message)
│
│                   elif isinstance(message, bytes):
│                       # 音频消息 -> AudioDataReceivedEvent
│                       await self._route_audio_message(session_id, message, context)
│
│               async def _route_text_message(self, session_id: str, text: str):
│                   """路由文本消息"""
│                   await self.event_bus.publish(TextMessageReceivedEvent(
│                       session_id=session_id,
│                       content=text,
│                       timestamp=time.time()
│                   ))
│
│               async def _route_audio_message(self, session_id: str, data: bytes, context):
│                   """路由音频消息"""
│                   # 检查是否来自MQTT网关
│                   if context.conn_from_mqtt_gateway and len(data) >= 16:
│                       # 解析MQTT头部
│                       timestamp = int.from_bytes(data[8:12], "big")
│                       audio_length = int.from_bytes(data[12:16], "big")
│
│                       if audio_length > 0 and len(data) >= 16 + audio_length:
│                           audio_data = data[16:16 + audio_length]
│                       else:
│                           audio_data = data[16:]
│
│                       # 发布带时间戳的音频事件
│                       await self.event_bus.publish(AudioDataReceivedEvent(
│                           session_id=session_id,
│                           data=audio_data,
│                           timestamp=timestamp
│                       ))
│                   else:
│                       # 普通音频数据
│                       await self.event_bus.publish(AudioDataReceivedEvent(
│                           session_id=session_id,
│                           data=data,
│                           timestamp=time.time()
│                       ))
│           ```
│
├── event/                                          [✨ 新增目录]
│   ├── __init__.py                                 [✨ 新增]
│   │
│   ├── event_bus.py                                [✨ 新增]
│   │   ├── 功能: 事件总线（核心解耦机制）
│   │   ├── 职责:
│   │   │   • 事件订阅/发布
│   │   │   • 事件分发
│   │   │   • 异步事件处理
│   │   └── 实现细节:
│   │       ```python
│   │       class EventBus:
│   │           """事件总线 - 模块间通信的核心"""
│   │
│   │           def __init__(self):
│   │               self._handlers: Dict[Type, List[Callable]] = defaultdict(list)
│   │               self._async_handlers: Dict[Type, List[Callable]] = defaultdict(list)
│   │               self.logger = setup_logging()
│   │               self._event_queue: asyncio.Queue = asyncio.Queue()
│   │               self._processing_task: Optional[asyncio.Task] = None
│   │
│   │           def subscribe(self, event_type: Type, handler: Callable, is_async: bool = True):
│   │               """订阅事件
│   │
│   │               Args:
│   │                   event_type: 事件类型
│   │                   handler: 事件处理函数
│   │                   is_async: 是否为异步处理器
│   │               """
│   │               if is_async:
│   │                   self._async_handlers[event_type].append(handler)
│   │               else:
│   │                   self._handlers[event_type].append(handler)
│   │
│   │               self.logger.debug(f"订阅事件: {event_type.__name__} -> {handler.__name__}")
│   │
│   │           def unsubscribe(self, event_type: Type, handler: Callable):
│   │               """取消订阅事件"""
│   │               if handler in self._async_handlers[event_type]:
│   │                   self._async_handlers[event_type].remove(handler)
│   │               if handler in self._handlers[event_type]:
│   │                   self._handlers[event_type].remove(handler)
│   │
│   │           async def publish(self, event: Any):
│   │               """发布事件（异步）"""
│   │               event_type = type(event)
│   │               self.logger.debug(f"发布事件: {event_type.__name__}")
│   │
│   │               # 同步处理器立即执行
│   │               for handler in self._handlers[event_type]:
│   │                   try:
│   │                       handler(event)
│   │                   except Exception as e:
│   │                       self.logger.error(f"同步事件处理失败 {handler.__name__}: {e}")
│   │
│   │               # 异步处理器并发执行
│   │               tasks = []
│   │               for handler in self._async_handlers[event_type]:
│   │                   tasks.append(self._safe_handle(handler, event))
│   │
│   │               if tasks:
│   │                   await asyncio.gather(*tasks, return_exceptions=True)
│   │
│   │           async def _safe_handle(self, handler: Callable, event: Any):
│   │               """安全执行处理器"""
│   │               try:
│   │                   await handler(event)
│   │               except Exception as e:
│   │                   self.logger.error(
│   │                       f"异步事件处理失败 {handler.__name__}: {e}\n"
│   │                       f"{traceback.format_exc()}"
│   │                   )
│   │
│   │           def start_processing(self):
│   │               """启动事件处理循环"""
│   │               if self._processing_task is None or self._processing_task.done():
│   │                   self._processing_task = asyncio.create_task(self._process_events())
│   │
│   │           async def _process_events(self):
│   │               """处理事件队列"""
│   │               while True:
│   │                   event = await self._event_queue.get()
│   │                   if event is None:  # 停止信号
│   │                       break
│   │                   await self.publish(event)
│   │
│   │           async def stop_processing(self):
│   │               """停止事件处理"""
│   │               await self._event_queue.put(None)
│   │               if self._processing_task:
│   │                   await self._processing_task
│   │       ```
│   │
│   ├── event_types.py                              [✨ 新增]
│   │   ├── 功能: 事件类型定义
│   │   ├── 职责: 定义所有事件的数据结构
│   │   └── 实现细节:
│   │       ```python
│   │       from dataclasses import dataclass
│   │       from typing import Any, Dict, Optional
│   │
│   │       # ==================== 基础事件 ====================
│   │       @dataclass
│   │       class Event:
│   │           """事件基类"""
│   │           session_id: str
│   │           timestamp: float
│   │
│   │       # ==================== 生命周期事件 ====================
│   │       @dataclass
│   │       class SessionCreatedEvent(Event):
│   │           """会话创建事件"""
│   │           device_id: Optional[str]
│   │           client_ip: str
│   │
│   │       @dataclass
│   │       class SessionDestroyingEvent(Event):
│   │           """会话销毁事件"""
│   │           pass
│   │
│   │       # ==================== 消息事件 ====================
│   │       @dataclass
│   │       class TextMessageReceivedEvent(Event):
│   │           """文本消息接收事件"""
│   │           content: str
│   │
│   │       @dataclass
│   │       class AudioDataReceivedEvent(Event):
│   │           """音频数据接收事件"""
│   │           data: bytes
│   │
│   │       # ==================== 音频处理事件 ====================
│   │       @dataclass
│   │       class SpeechDetectedEvent(Event):
│   │           """检测到语音事件"""
│   │           pass
│   │
│   │       @dataclass
│   │       class SpeechEndedEvent(Event):
│   │           """语音结束事件"""
│   │           audio_data: bytes
│   │
│   │       @dataclass
│   │       class TextRecognizedEvent(Event):
│   │           """文本识别完成事件"""
│   │           text: str
│   │           is_final: bool = True
│   │
│   │       # ==================== TTS 事件 ====================
│   │       @dataclass
│   │       class TTSStartEvent(Event):
│   │           """TTS开始事件"""
│   │           sentence_id: str
│   │
│   │       @dataclass
│   │       class TTSAudioReadyEvent(Event):
│   │           """TTS音频就绪事件"""
│   │           audio_data: bytes
│   │           text: Optional[str]
│   │           sentence_type: str
│   │
│   │       @dataclass
│   │       class TTSEndEvent(Event):
│   │           """TTS结束事件"""
│   │           sentence_id: str
│   │
│   │       # ==================== 意图事件 ====================
│   │       @dataclass
│   │       class IntentRecognizedEvent(Event):
│   │           """意图识别事件"""
│   │           intent_name: str
│   │           parameters: Dict[str, Any]
│   │
│   │       @dataclass
│   │       class FunctionCallRequestEvent(Event):
│   │           """函数调用请求事件"""
│   │           function_name: str
│   │           arguments: Dict[str, Any]
│   │           call_id: str
│   │
│   │       # ==================== 控制事件 ====================
│   │       @dataclass
│   │       class AbortRequestEvent(Event):
│   │           """中止请求事件"""
│   │           reason: str = "user_interrupt"
│   │
│   │       @dataclass
│   │       class PlayMusicRequestEvent(Event):
│   │           """播放音乐请求事件"""
│   │           music_path: str
│   │           song_name: str
│   │
│   │       # ==================== WebSocket 事件 ====================
│   │       @dataclass
│   │       class SendWebSocketMessageEvent(Event):
│   │           """发送WebSocket消息事件"""
│   │           data: Any
│   │           is_json: bool = True
│   │       ```
│   │
│   └── event_handler.py                            [✨ 新增]
│       ├── 功能: 事件处理器基类
│       ├── 职责: 提供事件处理器的基础实现
│       └── 实现细节:
│           ```python
│           class EventHandler(ABC):
│               """事件处理器基类"""
│
│               def __init__(self, container: DIContainer):
│                   self.container = container
│                   self.logger = setup_logging()
│
│               @abstractmethod
│               async def handle(self, event: Event):
│                   """处理事件"""
│                   pass
│
│               def supports(self, event_type: Type) -> bool:
│                   """检查是否支持该事件类型"""
│                   return False
│           ```
│
├── di/                                             [✨ 新增目录]
│   ├── __init__.py                                 [✨ 新增]
│   │
│   ├── container.py                                [✨ 新增]
│   │   ├── 功能: 依赖注入容器（核心解耦机制）
│   │   ├── 职责:
│   │   │   • 服务注册
│   │   │   • 服务解析
│   │   │   • 作用域管理（单例/会话级）
│   │   │   • 生命周期管理
│   │   └── 实现细节:
│   │       ```python
│   │       class ServiceScope(Enum):
│   │           """服务作用域"""
│   │           SINGLETON = "singleton"      # 全局单例
│   │           SESSION = "session"          # 会话级（每个会话一个实例）
│   │           TRANSIENT = "transient"      # 瞬态（每次解析创建新实例）
│   │
│   │       @dataclass
│   │       class ServiceRegistration:
│   │           """服务注册信息"""
│   │           name: str
│   │           factory: Callable
│   │           scope: ServiceScope
│   │           singleton_instance: Optional[Any] = None
│   │
│   │       class DIContainer:
│   │           """依赖注入容器"""
│   │
│   │           def __init__(self):
│   │               self._services: Dict[str, ServiceRegistration] = {}
│   │               self._session_scoped: Dict[str, Any] = {}  # key: "session_id:service_name"
│   │               self.logger = setup_logging()
│   │
│   │           def register(
│   │               self,
│   │               name: str,
│   │               factory: Callable,
│   │               scope: ServiceScope = ServiceScope.SINGLETON
│   │           ):
│   │               """注册服务
│   │
│   │               Args:
│   │                   name: 服务名称
│   │                   factory: 工厂函数，签名:
│   │                       - singleton: factory() -> instance
│   │                       - session: factory(session_id: str) -> instance
│   │                       - transient: factory(*args, **kwargs) -> instance
│   │                   scope: 服务作用域
│   │               """
│   │               self._services[name] = ServiceRegistration(
│   │                   name=name,
│   │                   factory=factory,
│   │                   scope=scope
│   │               )
│   │               self.logger.debug(f"注册服务: {name} (scope={scope.value})")
│   │
│   │           def resolve(self, name: str, session_id: Optional[str] = None, **kwargs) -> Any:
│   │               """解析服务
│   │
│   │               Args:
│   │                   name: 服务名称
│   │                   session_id: 会话ID（仅 session 作用域需要）
│   │                   **kwargs: 传递给工厂函数的参数（仅 transient 作用域）
│   │               """
│   │               service = self._services.get(name)
│   │               if not service:
│   │                   raise ValueError(f"服务 '{name}' 未注册")
│   │
│   │               if service.scope == ServiceScope.SINGLETON:
│   │                   # 单例模式
│   │                   if service.singleton_instance is None:
│   │                       service.singleton_instance = service.factory()
│   │                   return service.singleton_instance
│   │
│   │               elif service.scope == ServiceScope.SESSION:
│   │                   # 会话级作用域
│   │                   if not session_id:
│   │                       raise ValueError(f"服务 '{name}' 需要 session_id 参数")
│   │
│   │                   key = f"{session_id}:{name}"
│   │                   if key not in self._session_scoped:
│   │                       self._session_scoped[key] = service.factory(session_id)
│   │                   return self._session_scoped[key]
│   │
│   │               else:  # TRANSIENT
│   │                   # 瞬态模式，每次创建新实例
│   │                   return service.factory(**kwargs)
│   │
│   │           def cleanup_session(self, session_id: str):
│   │               """清理会话级服务"""
│   │               keys_to_remove = [
│   │                   key for key in self._session_scoped.keys()
│   │                   if key.startswith(f"{session_id}:")
│   │               ]
│   │               for key in keys_to_remove:
│   │                   del self._session_scoped[key]
│   │
│   │               self.logger.debug(f"清理会话服务: {session_id} ({len(keys_to_remove)} 个)")
│   │
│   │           def update_session_service(self, session_id: str, service_name: str, instance: Any):
│   │               """更新会话级服务实例（用于动态切换 ASR/TTS）"""
│   │               key = f"{session_id}:{service_name}"
│   │               self._session_scoped[key] = instance
│   │               self.logger.debug(f"更新会话服务: {key}")
│   │       ```
│   │
│   └── lifecycle.py                                [✨ 新增]
│       ├── 功能: 生命周期管理器
│       ├── 职责:
│       │   • 管理会话的启动/停止状态
│       │   • 提供事件循环访问
│       │   • 异步任务调度
│       └── 实现细节:
│           ```python
│           class LifecycleManager:
│               """生命周期管理器 - 替代 conn.stop_event 和 conn.loop"""
│
│               def __init__(self, session_id: str):
│                   self.session_id = session_id
│                   self.loop = asyncio.get_event_loop()
│                   self._stop_event = asyncio.Event()
│                   self._tasks: List[asyncio.Task] = []
│                   self.logger = setup_logging()
│
│               def is_stopped(self) -> bool:
│                   """检查是否已停止"""
│                   return self._stop_event.is_set()
│
│               def is_running(self) -> bool:
│                   """检查事件循环是否运行"""
│                   return self.loop.is_running()
│
│               async def execute_async(self, coro, *args, **kwargs):
│                   """在会话事件循环中执行异步任务"""
│                   if self.is_stopped():
│                       raise RuntimeError(f"会话 {self.session_id} 已停止")
│                   return await coro(*args, **kwargs)
│
│               def create_task(self, coro) -> asyncio.Task:
│                   """创建并跟踪任务"""
│                   if self.is_stopped():
│                       raise RuntimeError(f"会话 {self.session_id} 已停止")
│
│                   task = self.loop.create_task(coro)
│                   self._tasks.append(task)
│                   return task
│
│               async def stop(self):
│                   """停止会话"""
│                   self._stop_event.set()
│
│                   # 取消所有任务
│                   for task in self._tasks:
│                       if not task.done():
│                           task.cancel()
│
│                   # 等待任务完成
│                   if self._tasks:
│                       await asyncio.gather(*self._tasks, return_exceptions=True)
│
│                   self.logger.debug(f"会话 {self.session_id} 生命周期已停止")
│           ```
│
└── queue/                                          [✨ 新增目录]
    ├── __init__.py                                 [✨ 新增]
    │
    └── message_queue.py                            [✨ 新增]
        ├── 功能: 消息队列管理
        ├── 职责: 提供线程安全的队列操作
        └── 实现细节:
            ```python
            class MessageQueue:
                """消息队列包装器"""

                def __init__(self, maxsize: int = 0):
                    self._queue = queue.Queue(maxsize=maxsize)
                    self._async_queue = asyncio.Queue(maxsize=maxsize)

                def put(self, item: Any, block: bool = True, timeout: Optional[float] = None):
                    """同步放入"""
                    self._queue.put(item, block, timeout)

                async def async_put(self, item: Any):
                    """异步放入"""
                    await self._async_queue.put(item)

                def get(self, block: bool = True, timeout: Optional[float] = None) -> Any:
                    """同步获取"""
                    return self._queue.get(block, timeout)

                async def async_get(self) -> Any:
                    """异步获取"""
                    return await self._async_queue.get()

                def qsize(self) -> int:
                    """队列大小"""
                    return self._queue.qsize()

                def clear(self):
                    """清空队列"""
                    while not self._queue.empty():
                        try:
                            self._queue.get_nowait()
                        except queue.Empty:
                            break
            ```
```

---

### 4. core/domain/ 领域层（新增）

```
core/domain/
│
├── __init__.py                                     [✨ 新增]
│
├── services/                                       [✨ 新增目录]
│   ├── __init__.py                                 [✨ 新增]
│   │
│   ├── audio_service.py                            [✨ 新增]
│   │   ├── 功能: 音频处理服务（整合 VAD + ASR 逻辑）
│   │   ├── 职责:
│   │   │   • 音频数据接收
│   │   │   • VAD 检测
│   │   │   • ASR 识别
│   │   │   • 发布语音事件
│   │   ├── 替代: core/handle/receiveAudioHandle.py 的部分逻辑
│   │   └── 实现细节:
│   │       ```python
│   │       class AudioProcessingService:
│   │           """音频处理服务 - 整合 VAD + ASR"""
│   │
│   │           def __init__(self, container: DIContainer, event_bus: EventBus):
│   │               self.container = container
│   │               self.event_bus = event_bus
│   │               self.logger = setup_logging()
│   │
│   │           async def handle_audio_data(self, event: AudioDataReceivedEvent):
│   │               """处理音频数据事件"""
│   │               session_id = event.session_id
│   │               audio_data = event.data
│   │
│   │               # 获取服务
│   │               vad = self.container.resolve('vad')
│   │               asr = self.container.resolve('asr_service', session_id=session_id)
│   │               context = self.container.resolve('session_context', session_id=session_id)
│   │
│   │               # VAD 检测
│   │               have_voice = vad.is_vad(context, audio_data)
│   │
│   │               # 处理刚唤醒状态
│   │               if context.just_woken_up:
│   │                   have_voice = False
│   │                   if not hasattr(context, 'vad_resume_task') or context.vad_resume_task.done():
│   │                       context.vad_resume_task = asyncio.create_task(
│   │                           self._resume_vad_detection(context)
│   │                       )
│   │                   return
│   │
│   │               # 检测到语音，发布事件
│   │               if have_voice:
│   │                   # 如果正在说话且不是 manual 模式，中止当前播放
│   │                   if context.client_is_speaking and context.client_listen_mode != "manual":
│   │                       await self.event_bus.publish(AbortRequestEvent(
│   │                           session_id=session_id,
│   │                           timestamp=time.time(),
│   │                           reason="user_interrupt"
│   │                       ))
│   │
│   │                   # 发布语音检测事件
│   │                   if not context.client_have_voice:
│   │                       await self.event_bus.publish(SpeechDetectedEvent(
│   │                           session_id=session_id,
│   │                           timestamp=time.time()
│   │                       ))
│   │
│   │               # 传递给 ASR 服务
│   │               await asr.receive_audio(audio_data, have_voice)
│   │
│   │           async def _resume_vad_detection(self, context):
│   │               """恢复 VAD 检测"""
│   │               await asyncio.sleep(2)
│   │               context.just_woken_up = False
│   │       ```
│   │
│   ├── dialogue_service.py                         [✨ 新增]
│   │   ├── 功能: 对话管理服务（整合 LLM 交互逻辑）
│   │   ├── 职责:
│   │   │   • 对话历史管理
│   │   │   • LLM 调用
│   │   │   • 函数调用处理
│   │   │   • 记忆查询/保存
│   │   ├── 替代: ConnectionHandler.chat() 方法
│   │   └── 实现细节:
│   │       ```python
│   │       class DialogueService:
│   │           """对话服务 - 替代 ConnectionHandler.chat()"""
│   │
│   │           def __init__(self, container: DIContainer, event_bus: EventBus):
│   │               self.container = container
│   │               self.event_bus = event_bus
│   │               self.logger = setup_logging()
│   │
│   │           async def process_user_input(self, session_id: str, text: str, depth: int = 0):
│   │               """处理用户输入"""
│   │               context = self.container.resolve('session_context', session_id=session_id)
│   │               dialogue = self.container.resolve('dialogue', session_id=session_id)
│   │               llm = self.container.resolve('llm')
│   │               memory = self.container.resolve('memory_service', session_id=session_id)
│   │
│   │               # 首次调用时初始化
│   │               if depth == 0:
│   │                   context.llm_finish_task = False
│   │                   context.sentence_id = str(uuid.uuid4().hex)
│   │                   dialogue.put(Message(role="user", content=text))
│   │
│   │                   # 发布 TTS 开始事件
│   │                   await self.event_bus.publish(TTSStartEvent(
│   │                       session_id=session_id,
│   │                       timestamp=time.time(),
│   │                       sentence_id=context.sentence_id
│   │                   ))
│   │
│   │               # 检查最大深度
│   │               MAX_DEPTH = 5
│   │               force_final_answer = depth >= MAX_DEPTH
│   │
│   │               # 获取记忆
│   │               memory_str = None
│   │               if memory:
│   │                   memory_str = await memory.query_memory(text)
│   │
│   │               # 获取函数列表
│   │               functions = None
│   │               if context.get_config('Intent.type') == "function_call" and not force_final_answer:
│   │                   func_handler = self.container.resolve('function_handler', session_id=session_id)
│   │                   functions = func_handler.get_functions()
│   │
│   │               # 调用 LLM
│   │               response_chunks = []
│   │               tool_calls = []
│   │
│   │               try:
│   │                   if functions:
│   │                       llm_responses = llm.response_with_functions(
│   │                           context.session_id,
│   │                           dialogue.get_llm_dialogue_with_memory(memory_str),
│   │                           functions=functions
│   │                       )
│   │                   else:
│   │                       llm_responses = llm.response(
│   │                           context.session_id,
│   │                           dialogue.get_llm_dialogue_with_memory(memory_str)
│   │                       )
│   │
│   │                   # 处理流式响应
│   │                   async for chunk in llm_responses:
│   │                       if context.client_abort:
│   │                           break
│   │
│   │                       content, tools = self._parse_chunk(chunk, functions)
│   │
│   │                       if tools:
│   │                           tool_calls.extend(tools)
│   │
│   │                       if content:
│   │                           response_chunks.append(content)
│   │                           # 发布流式文本事件
│   │                           await self.event_bus.publish(TTSAudioReadyEvent(
│   │                               session_id=session_id,
│   │                               timestamp=time.time(),
│   │                               audio_data=content.encode(),
│   │                               text=content,
│   │                               sentence_type="middle"
│   │                           ))
│   │
│   │               except Exception as e:
│   │                   self.logger.error(f"LLM 处理失败: {e}")
│   │                   return
│   │
│   │               # 处理函数调用
│   │               if tool_calls:
│   │                   await self._handle_tool_calls(session_id, tool_calls, depth)
│   │
│   │               # 保存对话
│   │               if response_chunks:
│   │                   full_response = "".join(response_chunks)
│   │                   dialogue.put(Message(role="assistant", content=full_response))
│   │
│   │               # 结束标记
│   │               if depth == 0:
│   │                   await self.event_bus.publish(TTSEndEvent(
│   │                       session_id=session_id,
│   │                       timestamp=time.time(),
│   │                       sentence_id=context.sentence_id
│   │                   ))
│   │                   context.llm_finish_task = True
│   │
│   │           async def _handle_tool_calls(self, session_id: str, tool_calls: List, depth: int):
│   │               """处理工具调用"""
│   │               func_handler = self.container.resolve('function_handler', session_id=session_id)
│   │
│   │               # 并行执行工具调用
│   │               tasks = []
│   │               for tool_call in tool_calls:
│   │                   tasks.append(func_handler.execute_function(tool_call))
│   │
│   │               results = await asyncio.gather(*tasks, return_exceptions=True)
│   │
│   │               # 处理结果
│   │               need_llm = []
│   │               for result, tool_call in zip(results, tool_calls):
│   │                   if result.action == Action.REQLLM:
│   │                       need_llm.append((result, tool_call))
│   │                   elif result.action in [Action.RESPONSE, Action.ERROR]:
│   │                       # 直接回复
│   │                       text = result.response or result.result
│   │                       await self.event_bus.publish(TTSAudioReadyEvent(
│   │                           session_id=session_id,
│   │                           timestamp=time.time(),
│   │                           audio_data=text.encode(),
│   │                           text=text,
│   │                           sentence_type="middle"
│   │                       ))
│   │
│   │               # 递归调用 LLM
│   │               if need_llm:
│   │                   await self.process_user_input(session_id, None, depth + 1)
│   │       ```
│   │
│   ├── intent_service.py                           [✨ 新增]
│   │   ├── 功能: 意图识别服务
│   │   ├── 职责:
│   │   │   • 意图识别
│   │   │   • 意图路由
│   │   ├── 替代: core/handle/intentHandler.py 的部分逻辑
│   │   └── 实现细节:
│   │       ```python
│   │       class IntentService:
│   │           """意图识别服务"""
│   │
│   │           def __init__(self, container: DIContainer, event_bus: EventBus):
│   │               self.container = container
│   │               self.event_bus = event_bus
│   │               self.logger = setup_logging()
│   │
│   │           async def recognize_intent(self, session_id: str, text: str):
│   │               """识别意图"""
│   │               context = self.container.resolve('session_context', session_id=session_id)
│   │               intent_provider = self.container.resolve('intent')
│   │
│   │               intent_type = context.get_config('Intent.type')
│   │
│   │               if intent_type == "nointent":
│   │                   # 无意图识别，直接对话
│   │                   dialogue_service = self.container.resolve('dialogue_service')
│   │                   await dialogue_service.process_user_input(session_id, text)
│   │               else:
│   │                   # 执行意图识别
│   │                   result = await intent_provider.recognize(text)
│   │
│   │                   # 发布意图识别事件
│   │                   await self.event_bus.publish(IntentRecognizedEvent(
│   │                       session_id=session_id,
│   │                       timestamp=time.time(),
│   │                       intent_name=result.intent,
│   │                       parameters=result.parameters
│   │                   ))
│   │       ```
│   │
│   └── tts_orchestrator.py                         [✨ 新增]
│       ├── 功能: TTS 编排服务（替代直接操作 conn.tts）
│       ├── 职责:
│       │   • TTS 任务队列管理
│       │   • TTS 生成协调
│       │   • 音频发送协调
│       ├── 替代: 直接访问 conn.tts.tts_text_queue
│       └── 实现细节:
│           ```python
│           class TTSOrchestrator:
│               """TTS 编排服务 - 替代直接操作 conn.tts"""
│
│               def __init__(self, container: DIContainer, event_bus: EventBus):
│                   self.container = container
│                   self.event_bus = event_bus
│                   self.logger = setup_logging()
│
│               async def add_message(
│                   self,
│                   session_id: str,
│                   sentence_type: SentenceType,
│                   content_type: ContentType,
│                   content_detail: Optional[str] = None,
│                   content_file: Optional[str] = None
│               ):
│                   """添加 TTS 消息（替代 conn.tts.tts_text_queue.put）"""
│                   tts_provider = self.container.resolve('tts_provider', session_id=session_id)
│                   context = self.container.resolve('session_context', session_id=session_id)
│
│                   # 创建 TTS 消息
│                   message = TTSMessageDTO(
│                       sentence_id=context.sentence_id,
│                       sentence_type=sentence_type,
│                       content_type=content_type,
│                       content_detail=content_detail,
│                       content_file=content_file
│                   )
│
│                   # 放入 TTS 队列
│                   tts_provider.tts_text_queue.put(message)
│
│               async def synthesize_one_sentence(
│                   self,
│                   session_id: str,
│                   text: str
│               ):
│                   """合成单句（简化接口）"""
│                   context = self.container.resolve('session_context', session_id=session_id)
│
│                   await self.add_message(
│                       session_id=session_id,
│                       sentence_type=SentenceType.FIRST,
│                       content_type=ContentType.ACTION
│                   )
│
│                   await self.add_message(
│                       session_id=session_id,
│                       sentence_type=SentenceType.MIDDLE,
│                       content_type=ContentType.TEXT,
│                       content_detail=text
│                   )
│
│                   await self.add_message(
│                       session_id=session_id,
│                       sentence_type=SentenceType.LAST,
│                       content_type=ContentType.ACTION
│                   )
│
│               async def play_audio_file(self, session_id: str, file_path: str):
│                   """播放音频文件"""
│                   await self.add_message(
│                       session_id=session_id,
│                       sentence_type=SentenceType.MIDDLE,
│                       content_type=ContentType.FILE,
│                       content_file=file_path
│                   )
│
│               async def cleanup(self):
│                   """清理资源"""
│                   # 清空队列等操作
│                   pass
│           ```
│
├── events/                                         [✨ 新增目录]
│   ├── __init__.py                                 [✨ 新增]
│   │   └── 从 infrastructure/event/event_types.py 导出事件
│   │
│   ├── audio_events.py                             [✨ 新增]
│   │   └── 音频相关事件（已在 event_types.py 中定义，此处可为空或作为分类导出）
│   │
│   ├── text_events.py                              [✨ 新增]
│   │   └── 文本相关事件
│   │
│   └── lifecycle_events.py                         [✨ 新增]
│       └── 生命周期事件
│
└── models/                                         [✨ 新增目录]
    ├── __init__.py                                 [✨ 新增]
    │
    ├── session.py                                  [✨ 新增]
    │   ├── 功能: 会话模型（数据类）
    │   └── 实现细节: 定义会话相关的数据模型
    │
    └── config.py                                   [✨ 新增]
        ├── 功能: 配置模型（数据类）
        └── 实现细节: 定义配置相关的数据模型
```

---

### 5. core/handle/ 处理器层（修改）

```
core/handle/
│
├── __init__.py                                     [📦 保留]
│
├── helloHandle.py                                  [🔄 修改]
│   ├── 移除: 直接访问 conn.websocket
│   ├── 移除: 直接操作 conn 属性
│   ├── 新增: 转换为事件监听器
│   ├── 修改: handleHelloMessage 改为事件处理器
│   └── 实现细节:
│       ```python
│       class HelloMessageHandler(EventHandler):
│           """Hello消息处理器 - 重构为事件监听器"""
│
│           def __init__(self, container: DIContainer, event_bus: EventBus):
│               super().__init__(container)
│               self.event_bus = event_bus
│               self.ws_transport = container.resolve('websocket_transport')
│
│           async def handle(self, event: TextMessageReceivedEvent):
│               """处理 hello 消息"""
│               try:
│                   msg_json = json.loads(event.content)
│
│                   if msg_json.get("type") != "hello":
│                       return
│
│                   session_id = event.session_id
│                   context = self.container.resolve('session_context', session_id=session_id)
│
│                   # 处理音频参数
│                   if audio_params := msg_json.get("audio_params"):
│                       format_type = audio_params.get("format")
│                       self.logger.debug(f"客户端音频格式: {format_type}")
│                       context.audio_format = format_type
│                       context.welcome_msg["audio_params"] = audio_params
│
│                   # 处理特性
│                   if features := msg_json.get("features"):
│                       self.logger.debug(f"客户端特性: {features}")
│                       context.features = features
│
│                       # 处理 MCP
│                       if features.get("mcp"):
│                           from core.providers.tools.device_mcp import MCPClient
│                           context.mcp_client = MCPClient()
│                           # 发送 MCP 初始化消息（通过事件）
│                           await self.event_bus.publish(MCPInitializeRequestEvent(
│                               session_id=session_id,
│                               timestamp=time.time()
│                           ))
│
│                   # 通过传输层发送欢迎消息
│                   await self.ws_transport.send_json(session_id, context.welcome_msg)
│
│               except json.JSONDecodeError:
│                   pass
│
│       # 注册事件处理器
│       def register_hello_handler(container: DIContainer, event_bus: EventBus):
│           handler = HelloMessageHandler(container, event_bus)
│           event_bus.subscribe(TextMessageReceivedEvent, handler.handle)
│       ```
│
├── textHandle.py                                   [🔄 修改]
│   ├── 移除: handleTextMessage(conn, message) 签名
│   ├── 新增: 转换为事件监听器
│   └── 实现细节:
│       ```python
│       class TextMessageHandler(EventHandler):
│           """文本消息处理器 - 重构为事件监听器"""
│
│           def __init__(self, container: DIContainer, event_bus: EventBus):
│               super().__init__(container)
│               self.event_bus = event_bus
│
│           async def handle(self, event: TextMessageReceivedEvent):
│               """处理文本消息"""
│               session_id = event.session_id
│               content = event.content
│
│               try:
│                   msg_json = json.loads(content)
│                   msg_type = msg_json.get("type")
│
│                   # 根据消息类型分发到不同的处理器
│                   if msg_type == "hello":
│                       # hello 消息已由 HelloMessageHandler 处理
│                       pass
│                   elif msg_type == "abort":
│                       await self.event_bus.publish(AbortRequestEvent(
│                           session_id=session_id,
│                           timestamp=time.time(),
│                           reason="client_request"
│                       ))
│                   elif msg_type == "server":
│                       await self._handle_server_message(session_id, msg_json)
│                   # ... 其他消息类型
│
│               except json.JSONDecodeError:
│                   self.logger.error(f"解析文本消息失败: {content}")
│       ```
│
├── receiveAudioHandle.py                           [🔄 修改]
│   ├── 移除: handleAudioMessage(conn, audio) 函数
│   ├── 移除: 直接访问 conn.vad, conn.asr
│   ├── 新增: 转换为事件监听器
│   ├── 功能: 逻辑移至 domain/services/audio_service.py
│   └── 实现细节:
│       ```python
│       # 原 handleAudioMessage 函数的逻辑已移至 AudioProcessingService
│       # 此文件保留向后兼容的函数签名，内部委托给服务
│
│       async def handleAudioMessage(conn, audio):
│           """向后兼容接口（废弃）"""
│           warnings.warn(
│               "handleAudioMessage已废弃，请使用AudioProcessingService",
│               DeprecationWarning
│           )
│           # 委托给服务处理
│           ...
│       ```
│
├── sendAudioHandle.py                              [🔄 修改]
│   ├── 移除: 直接访问 conn.websocket.send()
│   ├── 新增: 通过 WebSocketTransport 发送
│   ├── 修改: sendAudioMessage, send_tts_message, send_stt_message 函数
│   └── 实现细节:
│       ```python
│       # 重构前: 直接访问 conn.websocket
│       # 重构后: 通过依赖注入获取传输层
│
│       async def sendAudioMessage(
│           session_id: str,
│           sentence_type: SentenceType,
│           opus_packets: List[bytes],
│           text: Optional[str],
│           ws_transport: WebSocketTransport
│       ):
│           """发送音频消息 - 重构版"""
│           message = {
│               "type": "audio",
│               "sentence_type": sentence_type.value,
│               "data": base64.b64encode(b''.join(opus_packets)).decode(),
│               "text": text
│           }
│           await ws_transport.send_json(session_id, message)
│
│       # 为了向后兼容，保留原函数签名但标记为废弃
│       async def sendAudioMessage_legacy(conn, sentence_type, opus_packets, text):
│           """向后兼容接口（废弃）"""
│           warnings.warn("请使用新的 sendAudioMessage 接口", DeprecationWarning)
│           # 从 conn 中提取 session_id 并委托给新接口
│           ...
│       ```
│
├── abortHandle.py                                  [🔄 修改]
│   ├── 移除: 直接操作 conn 状态
│   ├── 新增: 转换为事件监听器
│   └── 实现细节:
│       ```python
│       class AbortHandler(EventHandler):
│           """中止处理器 - 重构为事件监听器"""
│
│           async def handle(self, event: AbortRequestEvent):
│               """处理中止请求"""
│               session_id = event.session_id
│               context = self.container.resolve('session_context', session_id=session_id)
│
│               # 设置中止标志
│               context.client_abort = True
│
│               # 清空 TTS 队列
│               tts_service = self.container.resolve('tts_orchestrator', session_id=session_id)
│               await tts_service.cleanup()
│
│               self.logger.info(f"会话 {session_id} 已中止")
│       ```
│
├── intentHandler.py                                [🔄 修改]
│   ├── 移除: handle_user_intent(conn, text) 函数
│   ├── 功能: 逻辑移至 domain/services/intent_service.py
│   └── 向后兼容接口
│
├── reportHandle.py                                 [📦 保留]
│   ├── 保留上报逻辑
│   ├── 修改: 从 context 获取配置，而非 conn
│
├── textMessageHandler.py                           [📦 保留]
├── textMessageHandlerRegistry.py                   [📦 保留]
├── textMessageProcessor.py                         [📦 保留]
├── textMessageType.py                              [📦 保留]
│
└── textHandler/                                    [📦 保留目录]
    ├── helloMessageHandler.py                      [🔄 修改]
    │   └── 适配新的事件驱动架构
    ├── abortMessageHandler.py                      [🔄 修改]
    ├── listenMessageHandler.py                     [🔄 修改]
    ├── iotMessageHandler.py                        [🔄 修改]
    ├── mcpMessageHandler.py                        [🔄 修改]
    └── serverMessageHandler.py                     [🔄 修改]
        └── 所有 textHandler 都需要适配新架构：
            - 不再接收 conn 参数
            - 通过 DIContainer 获取服务
            - 通过 EventBus 发布事件
```

---

### 6. core/providers/ 提供者层（修改）

```
core/providers/
│
├── asr/                                            [📦 保留目录]
│   ├── base.py                                     [🔄 修改]
│   │   ├── 移除: self.conn 属性
│   │   ├── 新增: 接收 session_context 参数
│   │   ├── 修改: open_audio_channels 方法
│   │   │   └── 实现细节:
│   │   │       ```python
│   │   │       class ASRProviderBase(ABC):
│   │   │           def __init__(self, config, session_context: Optional['SessionContext'] = None):
│   │   │               self.config = config
│   │   │               self.context = session_context  # 替代 self.conn
│   │   │               self.interface_type = InterfaceType.LOCAL
│   │   │               self.logger = setup_logging()
│   │   │
│   │   │           async def open_audio_channels(self, context: 'SessionContext'):
│   │   │               """打开音频通道 - 接收 context 而非 conn"""
│   │   │               self.context = context
│   │   │               # 启动处理线程
│   │   │               ...
│   │   │       ```
│   │   │
│   │   ├── 所有具体 ASR 实现（aliyun.py, baidu.py, etc.）  [🔄 修改]
│   │   │   └── 适配 base.py 的修改
│   │   │
│   │   └── dto/dto.py                              [📦 保留]
│   │
├── tts/                                            [📦 保留目录]
│   ├── base.py                                     [🔄 修改]
│   │   ├── 移除: self.conn 属性
│   │   ├── 新增: 接收 session_context 参数
│   │   ├── 修改: 所有使用 self.conn.stop_event 的地方
│   │   │   └── 改为: self.context.lifecycle.is_stopped()
│   │   ├── 修改: 所有使用 self.conn.loop 的地方
│   │   │   └── 改为: self.context.lifecycle.loop
│   │   └── 实现细节:
│   │       ```python
│   │       class TTSProviderBase(ABC):
│   │           def __init__(self, config, session_context: Optional['SessionContext'], delete_audio_file):
│   │               self.config = config
│   │               self.context = session_context  # 替代 self.conn
│   │               self.delete_audio_file = delete_audio_file
│   │               self.interface_type = InterfaceType.NON_STREAM
│   │               self.tts_text_queue = queue.Queue()
│   │               self.tts_audio_queue = queue.Queue()
│   │               self.logger = setup_logging()
│   │
│   │           async def open_audio_channels(self, context: 'SessionContext'):
│   │               """打开音频通道 - 接收 context 而非 conn"""
│   │               self.context = context
│   │
│   │               # 启动处理线程，使用 context.lifecycle
│   │               context.lifecycle.create_task(self._process_tts_queue())
│   │
│   │           async def _process_tts_queue(self):
│   │               """处理 TTS 队列"""
│   │               while not self.context.lifecycle.is_stopped():
│   │                   try:
│   │                       message = self.tts_text_queue.get(timeout=1)
│   │                       # 处理消息...
│   │                   except queue.Empty:
│   │                       continue
│   │       ```
│   │
│   ├── 所有具体 TTS 实现                            [🔄 修改]
│   │   ├── aliyun_stream.py, edge.py, openai.py, etc.
│   │   └── 适配 base.py 的修改，替换所有 self.conn 引用
│   │
│   └── dto/dto.py                                  [📦 保留]
│
├── vad/                                            [📦 保留目录]
│   ├── base.py                                     [🔄 修改]
│   │   ├── 修改: is_vad 方法签名
│   │   │   └── 从 is_vad(conn, audio) 改为 is_vad(context, audio)
│   │   └── 实现细节:
│   │       ```python
│   │       class VADProviderBase(ABC):
│   │           @abstractmethod
│   │           def is_vad(self, context: 'SessionContext', audio: bytes) -> bool:
│   │               """VAD 检测 - 接收 context 而非 conn"""
│   │               pass
│   │       ```
│   │
│   └── silero.py                                   [🔄 修改]
│       └── 适配 base.py 的修改
│
├── llm/                                            [📦 保留目录]
│   └── 所有文件保留不变
│
├── intent/                                         [📦 保留目录]
│   └── 所有文件保留不变
│
├── memory/                                         [📦 保留目录]
│   └── 所有文件保留不变
│
├── tools/                                          [📦 保留目录]
│   ├── unified_tool_handler.py                     [🔄 修改]
│   │   ├── 移除: 直接访问 conn
│   │   ├── 新增: 通过 container 解析服务
│   │   └── 实现细节:
│   │       ```python
│   │       class UnifiedToolHandler:
│   │           def __init__(self, container: DIContainer, session_id: str):
│   │               self.container = container
│   │               self.session_id = session_id
│   │               self.logger = setup_logging()
│   │
│   │           async def handle_llm_function_call(self, tool_call_data: Dict):
│   │               """处理 LLM 函数调用"""
│   │               # 从容器获取函数注册表
│   │               registry = self.container.resolve('function_registry', session_id=self.session_id)
│   │
│   │               # 获取插件上下文（替代 conn）
│   │               plugin_context = PluginContext(
│   │                   session_id=self.session_id,
│   │                   container=self.container,
│   │                   event_bus=self.container.resolve('event_bus')
│   │               )
│   │
│   │               # 执行函数
│   │               func_name = tool_call_data['name']
│   │               func_item = registry.get_function(func_name)
│   │
│   │               if func_item.type == ToolType.SYSTEM_CTL:
│   │                   # 传递 plugin_context 而非 conn
│   │                   result = await func_item.func(plugin_context, **arguments)
│   │               else:
│   │                   result = await func_item.func(**arguments)
│   │
│   │               return result
│   │       ```
│   │
│   └── 其他工具文件                                 [📦 保留]
│
└── vllm/                                           [📦 保留目录]
    └── 所有文件保留不变
```

---

### 7. core/utils/ 工具层（部分修改）

```
core/utils/
│
├── modules_initialize.py                           [🔄 修改]
│   ├── 修改: 初始化函数适配新架构
│   └── 实现细节:
│       ```python
│       def initialize_tts(config, session_context: Optional['SessionContext'] = None):
│           """初始化 TTS - 支持传入 session_context"""
│           tts_type = config['selected_module']['TTS']
│           tts_config = config['TTS'][tts_type]
│
│           # 创建 TTS 实例时传入 session_context
│           tts_class = get_tts_class(tts_type)
│           tts = tts_class(tts_config, session_context, delete_audio_file=True)
│
│           return tts
│       ```
│
├── dialogue.py                                     [📦 保留]
├── util.py                                         [📦 保留]
├── asr.py, tts.py, vad.py, llm.py, etc.            [📦 保留]
└── 其他工具文件                                     [📦 保留]
```

---

### 8. plugins_func/ 插件层（重大修改）

```
plugins_func/
│
├── register.py                                     [🔄 修改]
│   ├── 新增: PluginContext 类（替代 conn）
│   ├── 修改: 所有插件函数签名
│   └── 实现细节:
│       ```python
│       @dataclass
│       class PluginContext:
│           """插件执行上下文 - 替代 conn 参数"""
│           session_id: str
│           container: DIContainer
│           event_bus: EventBus
│
│           def get_service(self, service_type: str) -> Any:
│               """获取服务"""
│               return self.container.resolve(service_type, session_id=self.session_id)
│
│           async def publish_event(self, event: Event):
│               """发布事件"""
│               await self.event_bus.publish(event)
│
│           def get_context(self) -> 'SessionContext':
│               """获取会话上下文"""
│               return self.container.resolve('session_context', session_id=self.session_id)
│
│           def get_config(self, key: str, default=None) -> Any:
│               """获取配置"""
│               context = self.get_context()
│               return context.get_config(key, default)
│
│       # 修改装饰器，支持 PluginContext
│       def register_function(name, desc, type=None):
│           def decorator(func):
│               # 包装函数，自动注入 PluginContext
│               @wraps(func)
│               async def wrapper(*args, **kwargs):
│                   # 如果第一个参数是 DIContainer，则创建 PluginContext
│                   if len(args) > 0 and isinstance(args[0], PluginContext):
│                       return await func(*args, **kwargs)
│                   else:
│                       # 向后兼容旧接口
│                       return await func(*args, **kwargs)
│
│               all_function_registry[name] = FunctionItem(name, desc, wrapper, type)
│               return wrapper
│           return decorator
│       ```
│
├── loadplugins.py                                  [📦 保留]
│
└── functions/                                      [📦 保留目录]
    ├── play_music.py                               [🔄 修改]
    │   ├── 移除: 接收 conn 参数
    │   ├── 新增: 接收 PluginContext 参数
    │   ├── 移除: conn.loop.create_task
    │   ├── 新增: context.lifecycle.create_task 或发布事件
    │   ├── 移除: conn.tts.tts_text_queue.put
    │   ├── 新增: context.get_service('tts_orchestrator').add_message
    │   └── 实现细节:
    │       ```python
    │       @register_function("play_music", play_music_function_desc, ToolType.SYSTEM_CTL)
    │       async def play_music(context: PluginContext, song_name: str):
    │           """播放音乐 - 重构版"""
    │           try:
    │               music_intent = f"播放音乐 {song_name}" if song_name != "random" else "随机播放音乐"
    │
    │               # 发布播放音乐事件（推荐方式）
    │               music_path = await prepare_music(song_name)
    │               await context.publish_event(PlayMusicRequestEvent(
    │                   session_id=context.session_id,
    │                   timestamp=time.time(),
    │                   music_path=music_path,
    │                   song_name=song_name
    │               ))
    │
    │               return ActionResponse(
    │                   action=Action.NONE,
    │                   result="指令已接收",
    │                   response="正在为您播放音乐"
    │               )
    │           except Exception as e:
    │               return ActionResponse(
    │                   action=Action.RESPONSE,
    │                   result=str(e),
    │                   response="播放音乐时出错了"
    │               )
    │
    │       # 事件处理器
    │       class PlayMusicEventHandler(EventHandler):
    │           async def handle(self, event: PlayMusicRequestEvent):
    │               """处理播放音乐事件"""
    │               session_id = event.session_id
    │
    │               # 获取服务
    │               tts_service = self.container.resolve('tts_orchestrator', session_id=session_id)
    │               dialogue_service = self.container.resolve('dialogue_service', session_id=session_id)
    │
    │               # 添加提示文本
    │               text = _get_random_play_prompt(event.song_name)
    │               await tts_service.add_message(
    │                   session_id=session_id,
    │                   sentence_type=SentenceType.MIDDLE,
    │                   content_type=ContentType.TEXT,
    │                   content_detail=text
    │               )
    │
    │               # 播放音乐文件
    │               await tts_service.add_message(
    │                   session_id=session_id,
    │                   sentence_type=SentenceType.MIDDLE,
    │                   content_type=ContentType.FILE,
    │                   content_file=event.music_path
    │               )
    │       ```
    │
    ├── get_time.py                                 [🔄 修改]
    │   └── 适配 PluginContext
    │
    ├── get_weather.py                              [🔄 修改]
    │   └── 适配 PluginContext
    │
    ├── change_role.py                              [🔄 修改]
    │   └── 适配 PluginContext
    │
    ├── handle_exit_intent.py                       [🔄 修改]
    │   └── 适配 PluginContext
    │
    ├── hass_*.py                                   [🔄 修改]
    │   └── 所有 Home Assistant 插件适配 PluginContext
    │
    └── 其他插件                                     [🔄 修改]
        └── 全部适配 PluginContext
```

---

### 9. config/ 配置层（保留）

```
config/
│
├── config_loader.py                                [📦 保留]
├── logger.py                                       [📦 保留]
├── manage_api_client.py                            [📦 保留]
└── settings.py                                     [📦 保留]
```

---

## 🚀 实施步骤
### 阶段 1: 基础设施搭建

1. ✅ 创建目录结构
   - [ ]
   ```bash
   mkdir -p core/infrastructure/{websocket,event,di,queue}
   mkdir -p core/application
   mkdir -p core/domain/{services,events,models}
   ```

2. ✅ 实现事件总线
   - [ ] core/infrastructure/event/event_bus.py
   - [ ] core/infrastructure/event/event_types.py
   - [ ] core/infrastructure/event/event_handler.py

3. ✅ 实现依赖注入容器
   - [ ] core/infrastructure/di/container.py
   - [ ] core/infrastructure/di/lifecycle.py

4. ✅ 实现 WebSocket 传输层
   - [ ] core/infrastructure/websocket/transport.py
   - [ ] core/infrastructure/websocket/message_router.py

### 阶段 2: 应用层实现

1. ✅ 实现会话管理
   - [ ] core/application/session_manager.py
   - [ ] core/application/context.py

2. ✅ 修改 websocket_server.py
   - [ ] 集成 DIContainer
   - [ ] 集成 EventBus
   - [ ] 重写 _handle_connection
   - [ ] 删除 core/connection.py

3. ✅ 修改 app.py
   - [ ] 初始化 DIContainer
   - [ ] 注册所有服务
   - [ ] 启动事件总线

### 阶段 3: 领域层实现

**状态**: ⬜ 未开始

1. ✅ 实现领域服务
   - [ ] core/domain/services/audio_service.py
   - [ ] core/domain/services/dialogue_service.py
   - [ ] core/domain/services/intent_service.py
   - [ ] core/domain/services/tts_orchestrator.py

2. ✅ 定义领域事件
   - [ ] core/domain/events/audio_events.py
   - [ ] core/domain/events/text_events.py
   - [ ] core/domain/events/lifecycle_events.py

3. ✅ 注册事件处理器
   - [ ] 所有领域服务注册到事件总线

### 阶段 4: 处理器层重构

**状态**: ⬜ 未开始

1. ✅ 重构 handle 层
   - [ ] core/handle/helloHandle.py -> 事件监听器
   - [ ] core/handle/textHandle.py -> 事件监听器
   - [ ] core/handle/abortHandle.py -> 事件监听器
   - [ ] core/handle/sendAudioHandle.py -> 使用 WebSocketTransport

2. ✅ 重构 textHandler 子模块
   - [ ] 所有 textHandler 适配新架构

### 阶段 5: 提供者层适配

**状态**: ⬜ 未开始

1. ✅ 修改 ASR 基类和实现
   - [ ] core/providers/asr/base.py
   - [ ] 所有具体 ASR 实现

2. ✅ 修改 TTS 基类和实现
   - [ ] core/providers/tts/base.py
   - [ ] 所有具体 TTS 实现

3. ✅ 修改 VAD 实现
   - [ ] core/providers/vad/base.py
   - [ ] core/providers/vad/silero.py

4. ✅ 修改工具处理器
   - [ ] core/providers/tools/unified_tool_handler.py

### 阶段 6: 插件层重构

**状态**: ⬜ 未开始

1. ✅ 实现 PluginContext
   - [ ] plugins_func/register.py

2. ✅ 重构所有插件
   - [ ] plugins_func/functions/play_music.py
   - [ ] plugins_func/functions/get_time.py
   - [ ] plugins_func/functions/get_weather.py
   - [ ] plugins_func/functions/change_role.py
   - [ ] plugins_func/functions/handle_exit_intent.py
   - [ ] plugins_func/functions/hass_*.py
   - [ ] plugins_func/functions/search_from_ragflow.py
   - [ ] plugins_func/functions/其他.py


