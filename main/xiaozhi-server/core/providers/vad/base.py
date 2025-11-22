from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.application.context import SessionContext


class VADProviderBase(ABC):
    @abstractmethod
    def is_vad(self, context: 'SessionContext', data: bytes) -> bool:
        """检测音频数据中的语音活动 - 接收 context 而非 conn"""
        pass
