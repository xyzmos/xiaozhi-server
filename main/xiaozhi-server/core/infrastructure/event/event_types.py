"""事件类型定义"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Event:
    """基础事件类"""
    session_id: str
    timestamp: float = 0.0


@dataclass
class SessionCreatedEvent(Event):
    """会话创建事件"""
    device_id: Optional[str] = None
    client_ip: str = ""


@dataclass
class SessionDestroyingEvent(Event):
    """会话销毁事件"""
    pass


@dataclass
class TextMessageReceivedEvent(Event):
    """文本消息接收事件"""
    content: str = ""


@dataclass
class AudioDataReceivedEvent(Event):
    """音频数据接收事件"""
    data: bytes = b""


@dataclass
class VADResultEvent(Event):
    """VAD检测结果事件"""
    is_speech: bool = False
    probability: float = 0.0


@dataclass
class VADSpeechStartEvent(Event):
    """VAD检测到语音开始事件"""
    pass


@dataclass
class VADSpeechEndEvent(Event):
    """VAD检测到语音结束事件"""
    pass


@dataclass
class ASRTranscriptEvent(Event):
    """ASR转录结果事件"""
    text: str = ""
    is_final: bool = False
    confidence: float = 0.0


@dataclass
class ASRErrorEvent(Event):
    """ASR错误事件"""
    error: str = ""


@dataclass
class LLMRequestEvent(Event):
    """LLM请求事件"""
    query: str = ""
    context: Optional[Dict[str, Any]] = None


@dataclass
class LLMResponseEvent(Event):
    """LLM响应事件"""
    content: str = ""
    sentence_id: Optional[str] = None
    is_final: bool = False
    tool_calls: Optional[list] = None


@dataclass
class LLMErrorEvent(Event):
    """LLM错误事件"""
    error: str = ""


@dataclass
class TTSRequestEvent(Event):
    """TTS请求事件"""
    text: str = ""
    sentence_id: Optional[str] = None
    priority: int = 0


@dataclass
class TTSAudioReadyEvent(Event):
    """TTS音频就绪事件"""
    audio_data: bytes = b""
    sentence_id: Optional[str] = None
    text: Optional[str] = None
    sentence_type: Optional[str] = None


@dataclass
class TTSErrorEvent(Event):
    """TTS错误事件"""
    error: str = ""
    sentence_id: Optional[str] = None


@dataclass
class IntentRecognizedEvent(Event):
    """意图识别事件"""
    intent: str = ""
    entities: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


@dataclass
class ToolCallRequestEvent(Event):
    """工具调用请求事件"""
    tool_name: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    tool_call_id: Optional[str] = None


@dataclass
class ToolCallResponseEvent(Event):
    """工具调用响应事件"""
    tool_call_id: str = ""
    result: Any = None
    error: Optional[str] = None


@dataclass
class ClientAbortEvent(Event):
    """客户端中止事件"""
    reason: str = ""


@dataclass
class ClientSpeakingStateEvent(Event):
    """客户端说话状态事件"""
    is_speaking: bool = False


@dataclass
class WelcomeMessageEvent(Event):
    """欢迎消息事件"""
    message: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConfigUpdateEvent(Event):
    """配置更新事件"""
    key: str = ""
    value: Any = None


@dataclass
class ErrorEvent(Event):
    """通用错误事件"""
    error_type: str = ""
    error_message: str = ""
    exception: Optional[Exception] = None
