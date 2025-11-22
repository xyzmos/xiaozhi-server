"""WebSocket 传输层 - 负责底层数据发送"""

import asyncio
import json
from typing import Dict, Union

from config.logger import setup_logging


class WebSocketTransport:
    """WebSocket 传输层 - 管理 WebSocket 连接和数据发送"""

    def __init__(self):
        self._connections: Dict[str, any] = {}  # session_id -> websocket
        self._send_locks: Dict[str, asyncio.Lock] = {}
        self.logger = setup_logging()

    def register(self, session_id: str, websocket):
        """注册会话的 WebSocket 连接

        Args:
            session_id: 会话ID
            websocket: WebSocket 连接对象
        """
        self._connections[session_id] = websocket
        self._send_locks[session_id] = asyncio.Lock()
        self.logger.debug(f"WebSocket 已注册: {session_id}")

    def unregister(self, session_id: str):
        """注销会话连接

        Args:
            session_id: 会话ID
        """
        self._connections.pop(session_id, None)
        self._send_locks.pop(session_id, None)
        self.logger.debug(f"WebSocket 已注销: {session_id}")

    async def send(self, session_id: str, data: Union[str, bytes]):
        """发送数据到指定会话

        Args:
            session_id: 会话ID
            data: 要发送的数据（字符串或字节）

        Raises:
            ValueError: 如果会话不存在
        """
        ws = self._connections.get(session_id)
        if not ws:
            raise ValueError(f"会话 {session_id} 的 WebSocket 不存在")

        # 使用锁保证线程安全
        async with self._send_locks[session_id]:
            try:
                await ws.send(data)
            except Exception as e:
                self.logger.error(f"发送数据失败 {session_id}: {e}", exc_info=True)
                raise

    async def send_json(self, session_id: str, data: Dict):
        """发送 JSON 数据

        Args:
            session_id: 会话ID
            data: 要发送的字典数据
        """
        await self.send(session_id, json.dumps(data))

    async def send_text(self, session_id: str, text: str):
        """发送文本数据

        Args:
            session_id: 会话ID
            text: 要发送的文本
        """
        await self.send(session_id, text)

    async def send_binary(self, session_id: str, data: bytes):
        """发送二进制数据

        Args:
            session_id: 会话ID
            data: 要发送的二进制数据
        """
        await self.send(session_id, data)

    def is_connected(self, session_id: str) -> bool:
        """检查会话是否连接

        Args:
            session_id: 会话ID

        Returns:
            是否已连接
        """
        ws = self._connections.get(session_id)
        if not ws:
            return False
        return not ws.closed if hasattr(ws, 'closed') else True

    def get_connection(self, session_id: str):
        """获取会话的 WebSocket 连接

        Args:
            session_id: 会话ID

        Returns:
            WebSocket 连接对象或 None
        """
        return self._connections.get(session_id)

    def get_session_count(self) -> int:
        """获取当前连接的会话数"""
        return len(self._connections)

    def get_all_session_ids(self) -> list:
        """获取所有会话ID"""
        return list(self._connections.keys())
