import uuid
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class SessionContext:

    # Session唯一标识
    session_id: str

    # 设备基本信息
    device_id: Optional[str]
    client_ip: Optional[str]

    # 设备端音频相关参数信息,可用作后续编解码参数注入
    audio_format: dict[str, Any]

    # 设备端功能特性，是否支持MCP等
    features: dict[str, Any]

    # 客户端状态相关
    client_abort: Optional[bool] = False
    client_is_speaking: Optional[bool] = False
    client_listen_mode: Optional[str] = "auto"

    last_activity_time: float = 0.0

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())

    def __setattr__(self, key, value):
        if hasattr(self, "session_id") and key == "session_id":
            raise AttributeError("session_id is read-only and cannot be modified")
        super().__setattr__(key, value)

    def as_dict(self) -> dict:
        return self.__dict__.copy()
