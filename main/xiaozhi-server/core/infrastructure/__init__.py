"""基础设施层 - 提供核心基础设施组件"""

from core.infrastructure.di import DIContainer, LifecycleManager, ServiceScope
from core.infrastructure.event import EventBus, EventHandler, event_handler
from core.infrastructure.websocket import WebSocketMessageRouter, WebSocketTransport

__all__ = [
    'DIContainer',
    'ServiceScope',
    'LifecycleManager',
    'EventBus',
    'EventHandler',
    'event_handler',
    'WebSocketTransport',
    'WebSocketMessageRouter',
]
