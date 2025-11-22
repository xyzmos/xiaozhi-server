"""会话上下文 - 替代 ConnectionHandler 的状态管理部分"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from core.infrastructure.di.lifecycle import LifecycleManager


@dataclass
class SessionContext:
    """会话上下文 - 存储会话级别的状态和配置"""

    # 会话标识
    session_id: str
    device_id: Optional[str]
    client_id: Optional[str]
    client_ip: str

    # 配置
    _config: Dict[str, Any]

    # 生命周期管理器
    lifecycle: LifecycleManager

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

    # Dialogue
    dialogue: Optional[Any] = None

    # Prompt
    prompt: Optional[str] = None

    # Prompt manager
    prompt_manager: Optional[Any] = None

    # Voiceprint provider
    voiceprint_provider: Optional[Any] = None

    # Intent type
    intent_type: str = "nointent"

    # Load function plugin
    load_function_plugin: bool = False

    # MCP 客户端
    mcp_client: Optional[Any] = None

    # 工具处理器
    func_handler: Optional[Any] = None

    # IOT descriptors
    iot_descriptors: Dict[str, Any] = field(default_factory=dict)

    # DI Container reference
    container: Optional[Any] = None

    # Logger reference
    logger: Optional[Any] = None

    # Event loop reference (for thread-safe async operations)
    _event_loop: Optional[Any] = None

    # Headers from connection
    headers: Dict[str, str] = field(default_factory=dict)

    # ASR audio buffer
    asr_audio: list = field(default_factory=list)

    # Audio flow control for streaming
    audio_flow_control: Dict[str, Any] = field(default_factory=dict)

    # Configuration flags
    read_config_from_api: bool = False
    report_tts_enable: bool = False
    report_asr_enable: bool = False
    chat_history_conf: int = 0
    max_output_size: int = 0

    # Report queue
    report_queue: Optional[Any] = None

    # Command exit phrases
    cmd_exit: list = field(default_factory=list)

    # Intent provider
    intent: Optional[Any] = None

    # WebSocket server reference
    server: Optional[Any] = None

    # Property alias for backward compatibility
    @property
    def config(self) -> Dict[str, Any]:
        """Backward compatibility: access _config as config"""
        return self._config

    @property
    def stop_event(self):
        """Access stop_event from lifecycle manager"""
        return self.lifecycle._stop_event if self.lifecycle else None

    @property
    def loop(self):
        """Get the event loop (thread-safe)"""
        return self._event_loop

    def get_config(self, key: str, default=None) -> Any:
        """获取配置项

        Args:
            key: 配置键，支持点分隔的路径，如 'xiaozhi.name'
            default: 默认值

        Returns:
            配置值或默认值
        """
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k, default)
            else:
                return default
        return value if value is not None else default

    def update_config(self, key: str, value: Any):
        """更新配置项

        Args:
            key: 配置键，支持点分隔的路径
            value: 配置值
        """
        keys = key.split('.')
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value

    def update_activity_time(self):
        """更新活动时间"""
        self.last_activity_time = time.time() * 1000

    def reset_vad_states(self):
        """重置VAD状态"""
        self.client_have_voice = False
        self.client_voice_stop = False
        self.last_is_voice = False

    def get_timeout_seconds(self) -> int:
        """获取超时时间（秒）"""
        return int(self.get_config('close_connection_no_voice_time', 120)) + 60

    async def close(self):
        """关闭连接 - 通过 WebSocket 传输层和生命周期管理器"""
        if self.container:
            try:
                # 通过传输层关闭 WebSocket
                ws_transport = self.container.resolve('websocket_transport')
                await ws_transport.close(self.session_id)
            except Exception as e:
                if self.logger:
                    self.logger.error(f"关闭 WebSocket 连接失败: {e}")

        # 停止生命周期
        if self.lifecycle:
            await self.lifecycle.stop()
