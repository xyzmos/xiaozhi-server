import asyncio
import websockets
from typing import Dict, Any
from config.logger import setup_logging
from core.services.connection_service import ConnectionService
from core.transport.websocket_transport import WebSocketTransport
from config.config_loader import get_config_from_api
from core.utils.util import check_vad_update, check_asr_update

logger = setup_logging()


class NewWebSocketServer:
    """
    新的WebSocket服务器：使用新架构替代旧的ConnectionHandler
    集成ConnectionService、MessageRouter和新的Processor架构
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = setup_logging()
        self.config_lock = asyncio.Lock()
        
        # 创建连接服务
        self.connection_service = ConnectionService(config)
        
        # 活跃连接管理
        self.active_connections = set()
    
    async def start(self):
        """启动WebSocket服务器"""
        server_config = self.config["server"]
        host = server_config.get("ip", "0.0.0.0")
        port = int(server_config.get("port", 8000))
        
        logger.info(f"启动新架构WebSocket服务器: {host}:{port}")
        
        async with websockets.serve(
            self._handle_connection, 
            host, 
            port, 
            process_request=self._http_response
        ):
            logger.info("WebSocket服务器启动成功")
            await asyncio.Future()  # 保持服务器运行
    
    async def _handle_connection(self, websocket):
        """处理新连接 - 使用新架构"""
        # 提取连接头信息
        headers = self._extract_headers(websocket)
        
        # 创建WebSocket传输层
        transport = WebSocketTransport(websocket)
        
        # 记录活跃连接
        self.active_connections.add(transport)
        
        try:
            logger.info(f"新连接建立: {headers.get('device-id', 'unknown')} from {headers.get('x-real-ip', 'unknown')}")
            
            # 使用ConnectionService处理连接
            await self.connection_service.handle_connection(transport, headers)
            
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket连接正常关闭")
        except Exception as e:
            logger.error(f"处理WebSocket连接时出错: {e}", exc_info=True)
        finally:
            # 确保从活动连接集合中移除
            self.active_connections.discard(transport)
            
            # 强制关闭连接（如果还没有关闭的话）
            try:
                if hasattr(websocket, "closed") and not websocket.closed:
                    await websocket.close()
                elif hasattr(websocket, "state") and websocket.state.name != "CLOSED":
                    await websocket.close()
            except Exception as close_error:
                logger.error(f"强制关闭WebSocket连接时出错: {close_error}")
    
    def _extract_headers(self, websocket) -> Dict[str, str]:
        """从WebSocket请求中提取头信息"""
        headers = {}
        
        # 提取请求头
        if hasattr(websocket, 'request_headers'):
            for name, value in websocket.request_headers.items():
                headers[name.lower()] = value
        
        # 提取路径参数（如果有的话）
        if hasattr(websocket, 'path'):
            # 可以从路径中提取device-id等参数
            # 例如: /ws?device-id=xxx&client-id=yyy
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(websocket.path)
            query_params = parse_qs(parsed.query)
            
            for key, values in query_params.items():
                if values:
                    headers[key] = values[0]
        
        # 提取远程地址
        if hasattr(websocket, 'remote_address'):
            headers['x-real-ip'] = websocket.remote_address[0]
        
        return headers
    
    async def _http_response(self, websocket, request_headers):
        """处理HTTP请求"""
        # 检查是否为 WebSocket 升级请求
        if request_headers.headers.get("connection", "").lower() == "upgrade":
            # 如果是 WebSocket 请求，返回 None 允许握手继续
            return None
        else:
            # 如果是普通 HTTP 请求，返回服务器状态
            return websocket.respond(200, "New Architecture WebSocket Server is running\n")
    
    async def update_config(self) -> bool:
        """
        更新服务器配置并重新初始化组件
        
        Returns:
            bool: 更新是否成功
        """
        try:
            async with self.config_lock:
                logger.info("开始更新服务器配置")
                
                # 重新获取配置
                new_config = get_config_from_api(self.config)
                if new_config is None:
                    logger.error("获取新配置失败")
                    return False
                
                logger.info("获取新配置成功")
                
                # 检查配置变化
                config_changed = self._check_config_changes(self.config, new_config)
                
                # 更新配置
                self.config = new_config
                
                # 重新创建连接服务（如果配置有重大变化）
                if config_changed:
                    logger.info("配置有重大变化，重新创建连接服务")
                    self.connection_service = ConnectionService(new_config)
                
                logger.info("配置更新任务执行完毕")
                return True
                
        except Exception as e:
            logger.error(f"更新服务器配置失败: {str(e)}", exc_info=True)
            return False
    
    def _check_config_changes(self, old_config: Dict[str, Any], new_config: Dict[str, Any]) -> bool:
        """检查配置是否有重大变化"""
        # 检查关键配置项是否变化
        key_configs = [
            "selected_module",
            "vad",
            "asr", 
            "llm",
            "tts",
            "memory",
            "intent"
        ]
        
        for key in key_configs:
            if old_config.get(key) != new_config.get(key):
                logger.info(f"配置项 {key} 发生变化")
                return True
        
        return False
    
    def get_active_connections_count(self) -> int:
        """获取活跃连接数"""
        return len(self.active_connections)
    
    def get_server_status(self) -> Dict[str, Any]:
        """获取服务器状态"""
        return {
            "active_connections": self.get_active_connections_count(),
            "server_type": "new_architecture",
            "processors": self.connection_service.message_router.list_processors()
        }

