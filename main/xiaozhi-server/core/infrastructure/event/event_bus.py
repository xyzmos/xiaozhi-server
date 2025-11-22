"""事件总线 - 模块间通信的核心"""

import asyncio
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Type

from config.logger import setup_logging


class EventBus:
    """事件总线 - 负责事件的发布和订阅"""

    def __init__(self):
        self._handlers: Dict[Type, List[Callable]] = defaultdict(list)
        self._async_handlers: Dict[Type, List[Callable]] = defaultdict(list)
        self.logger = setup_logging()
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._processing_task: Optional[asyncio.Task] = None
        self._running = False

    def subscribe(self, event_type: Type, handler: Callable, is_async: bool = True):
        """订阅事件

        Args:
            event_type: 事件类型
            handler: 事件处理函数
            is_async: 是否为异步处理器
        """
        if is_async:
            self._async_handlers[event_type].append(handler)
        else:
            self._handlers[event_type].append(handler)

        self.logger.debug(f"订阅事件: {event_type.__name__} -> {handler.__name__}")

    def unsubscribe(self, event_type: Type, handler: Callable):
        """取消订阅事件"""
        if handler in self._async_handlers[event_type]:
            self._async_handlers[event_type].remove(handler)
        if handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)

        self.logger.debug(f"取消订阅事件: {event_type.__name__} -> {handler.__name__}")

    async def publish(self, event: Any):
        """发布事件（异步）

        Args:
            event: 事件对象
        """
        event_type = type(event)
        self.logger.debug(f"发布事件: {event_type.__name__}")

        # 同步处理器立即执行
        for handler in self._handlers[event_type]:
            try:
                handler(event)
            except Exception as e:
                self.logger.error(f"同步事件处理器执行失败 {handler.__name__}: {e}", exc_info=True)

        # 异步处理器并发执行
        tasks = []
        for handler in self._async_handlers[event_type]:
            task = asyncio.create_task(self._safe_call_handler(handler, event))
            tasks.append(task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_call_handler(self, handler: Callable, event: Any):
        """安全调用异步处理器"""
        try:
            await handler(event)
        except Exception as e:
            self.logger.error(f"异步事件处理器执行失败 {handler.__name__}: {e}", exc_info=True)

    def start(self):
        """启动事件总线"""
        if self._running:
            self.logger.warning("事件总线已在运行")
            return

        self._running = True
        self.logger.info("事件总线已启动")

    async def stop(self):
        """停止事件总线"""
        if not self._running:
            return

        self._running = False

        # 等待所有待处理的任务完成
        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass

        self.logger.info("事件总线已停止")

    def clear(self):
        """清空所有订阅"""
        self._handlers.clear()
        self._async_handlers.clear()
        self.logger.info("事件总线订阅已清空")
