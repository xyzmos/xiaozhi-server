"""事件处理器装饰器和基类"""

from typing import Callable, Type

from core.infrastructure.event.event_bus import EventBus
from core.infrastructure.event.event_types import Event


def event_handler(event_type: Type[Event], is_async: bool = True):
    """事件处理器装饰器

    Args:
        event_type: 事件类型
        is_async: 是否为异步处理器

    Example:
        @event_handler(AudioDataReceivedEvent)
        async def handle_audio(event: AudioDataReceivedEvent):
            pass
    """
    def decorator(func: Callable):
        func._event_type = event_type
        func._is_async = is_async
        return func
    return decorator


class EventHandler:
    """事件处理器基类"""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._register_handlers()

    def _register_handlers(self):
        """自动注册所有带装饰器的处理器方法"""
        for attr_name in dir(self):
            if attr_name.startswith('_'):
                continue

            attr = getattr(self, attr_name)
            if callable(attr) and hasattr(attr, '_event_type'):
                event_type = attr._event_type
                is_async = getattr(attr, '_is_async', True)
                self.event_bus.subscribe(event_type, attr, is_async=is_async)

    def unregister_all(self):
        """取消注册所有处理器"""
        for attr_name in dir(self):
            if attr_name.startswith('_'):
                continue

            attr = getattr(self, attr_name)
            if callable(attr) and hasattr(attr, '_event_type'):
                event_type = attr._event_type
                self.event_bus.unsubscribe(event_type, attr)
