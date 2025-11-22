"""生命周期管理器"""

import asyncio
from enum import Enum
from typing import Callable, List, Optional

from config.logger import setup_logging


class LifecycleState(Enum):
    """生命周期状态"""
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class LifecycleManager:
    """生命周期管理器 - 管理服务的启动和停止"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state = LifecycleState.CREATED
        self._on_start_callbacks: List[Callable] = []
        self._on_stop_callbacks: List[Callable] = []
        self._stop_event = asyncio.Event()
        self.logger = setup_logging()

    def on_start(self, callback: Callable):
        """注册启动回调

        Args:
            callback: 启动时执行的回调函数（可以是同步或异步）
        """
        self._on_start_callbacks.append(callback)

    def on_stop(self, callback: Callable):
        """注册停止回调

        Args:
            callback: 停止时执行的回调函数（可以是同步或异步）
        """
        self._on_stop_callbacks.append(callback)

    async def start(self):
        """启动生命周期"""
        if self.state != LifecycleState.CREATED:
            self.logger.warning(f"会话 {self.session_id} 生命周期已启动，状态: {self.state}")
            return

        self.state = LifecycleState.STARTING
        self.logger.info(f"会话 {self.session_id} 生命周期启动中...")

        try:
            # 执行所有启动回调
            for callback in self._on_start_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback()
                    else:
                        callback()
                except Exception as e:
                    self.logger.error(f"启动回调执行失败: {e}", exc_info=True)

            self.state = LifecycleState.RUNNING
            self._stop_event.clear()
            self.logger.info(f"会话 {self.session_id} 生命周期已启动")

        except Exception as e:
            self.state = LifecycleState.ERROR
            self.logger.error(f"会话 {self.session_id} 生命周期启动失败: {e}", exc_info=True)
            raise

    async def stop(self):
        """停止生命周期"""
        if self.state in (LifecycleState.STOPPED, LifecycleState.STOPPING):
            self.logger.debug(f"会话 {self.session_id} 生命周期已停止或正在停止")
            return

        self.state = LifecycleState.STOPPING
        self.logger.info(f"会话 {self.session_id} 生命周期停止中...")

        try:
            # 执行所有停止回调（逆序执行）
            for callback in reversed(self._on_stop_callbacks):
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback()
                    else:
                        callback()
                except Exception as e:
                    self.logger.error(f"停止回调执行失败: {e}", exc_info=True)

            self.state = LifecycleState.STOPPED
            self._stop_event.set()
            self.logger.info(f"会话 {self.session_id} 生命周期已停止")

        except Exception as e:
            self.state = LifecycleState.ERROR
            self.logger.error(f"会话 {self.session_id} 生命周期停止失败: {e}", exc_info=True)
            raise

    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self.state == LifecycleState.RUNNING

    def is_stopped(self) -> bool:
        """检查是否已停止"""
        return self.state == LifecycleState.STOPPED

    async def wait_for_stop(self):
        """等待生命周期停止"""
        await self._stop_event.wait()

    def __repr__(self):
        return f"LifecycleManager(session={self.session_id}, state={self.state.value})"
