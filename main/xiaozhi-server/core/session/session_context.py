import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SessionContext:

    # Session唯一标识
    session_id: str

    # 设备基本信息
    device_id: Optional[str] = None
    client_ip: Optional[str] = None

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
