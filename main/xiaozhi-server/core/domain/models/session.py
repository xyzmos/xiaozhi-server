"""会话模型"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from enum import Enum


class SessionState(str, Enum):
    """会话状态"""
    CREATED = "created"
    CONNECTED = "connected"
    ACTIVE = "active"
    SPEAKING = "speaking"
    LISTENING = "listening"
    PROCESSING = "processing"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass
class SessionInfo:
    """会话信息"""
    session_id: str
    device_id: Optional[str] = None
    client_id: Optional[str] = None
    client_ip: str = ""
    state: SessionState = SessionState.CREATED
    created_at: float = 0.0
    last_activity: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'session_id': self.session_id,
            'device_id': self.device_id,
            'client_id': self.client_id,
            'client_ip': self.client_ip,
            'state': self.state.value,
            'created_at': self.created_at,
            'last_activity': self.last_activity,
            'metadata': self.metadata,
        }


@dataclass
class DialogueMessage:
    """对话消息"""
    role: str
    content: str
    timestamp: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallInfo:
    """工具调用信息"""
    tool_id: str
    tool_name: str
    parameters: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None
    completed: bool = False
