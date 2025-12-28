import asyncio
from typing import Dict, Any
from urllib.parse import parse_qs, urlparse

from core.context.session_context import SessionContext
from core.transport.transport_interface import TransportInterface
from core.components.component_registry import ComponentRegistry
from core.components.component_manager import ComponentType
from core.pipeline.message_pipeline import MessagePipeline
from core.processors.message_router import MessageRouter
from config.logger import setup_logging

logger = setup_logging()


class ConnectionService:
    """连接服务：统一管理连接生命周期，替代ConnectionHandler"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = setup_logging()
        
        # 创建统一消息路由器
        self.message_router = MessageRouter()
        
        # 创建消息处理管道
        self.message_pipeline = MessagePipeline()
        self._setup_pipeline()
    
    def _setup_pipeline(self):
        """设置消息处理管道"""
        # 使用统一的MessageRouter替代单独的processor
        self.message_pipeline.add_processor(self.message_router)
    
    async def handle_connection(self, transport: TransportInterface, headers: Dict[str, str]):
        """处理新连接"""
        # 创建会话上下文
        context = SessionContext()
        context.config = self.config
        context.headers = headers
        
        # 设置transport接口
        context.transport = transport
        
        # 传入共享 ASR 管理器（如果有）
        # 这使得 ASRAdapter 可以使用预加载的模型实例
        if '_shared_asr_manager' in self.config:
            context.shared_asr_manager = self.config['_shared_asr_manager']
            logger.debug("连接使用共享 ASR 实例")
        
        # 兼容性：设置websocket属性（如果transport是WebSocket）
        if hasattr(transport, '_websocket'):
            context.websocket = transport._websocket
        
        # 从headers或URL参数中提取设备信息
        await self._extract_device_info(context, headers)
        
        # 创建组件管理器
        component_manager = ComponentRegistry.create_component_manager(self.config)
        
        # 启动超时检查任务
        timeout_task = None
        
        try:
            logger.info(f"新连接建立: {context.device_id} from {context.client_ip}")
            
            # 初始化必要的组件
            await self._initialize_components(context, component_manager)
            
            # 启动超时检查
            timeout_task = asyncio.create_task(self._check_timeout(context, transport))
            
            # 处理消息流
            async for message in transport.receive():
                try:
                    await self.message_pipeline.process_message(context, transport, message)
                except Exception as e:
                    logger.error(f"处理消息时出错: {e}")
                    # 继续处理其他消息，不中断连接
                    
        except Exception as e:
            logger.error(f"连接处理出错: {e}")
        finally:
            # 清理资源
            if timeout_task and not timeout_task.done():
                timeout_task.cancel()
                try:
                    await timeout_task
                except asyncio.CancelledError:
                    pass
            
            # 清理组件
            try:
                await component_manager.cleanup_all()
            except Exception as e:
                logger.error(f"组件清理失败: {e}")
            
            # 执行会话清理回调
            try:
                await context.run_cleanup()
            except Exception as e:
                logger.error(f"会话清理失败: {e}")
            
            # 关闭传输层
            try:
                await transport.close()
            except Exception as e:
                logger.error(f"关闭传输层失败: {e}")
            
            logger.info(f"连接已关闭: {context.device_id}")
    
    async def _extract_device_info(self, context: SessionContext, headers: Dict[str, str]):
        """从headers或URL参数中提取设备信息"""
        device_id = headers.get("device-id")
        client_id = headers.get("client-id")
        
        # 如果headers中没有device-id，尝试从URL参数中获取
        if not device_id:
            # 这里需要从WebSocket请求中获取路径信息
            # 暂时使用占位符，后续在WebSocketServer中传入
            pass
        
        context.device_id = device_id
        context.client_ip = headers.get("x-real-ip") or headers.get("x-forwarded-for", "unknown")
        
        if context.client_ip and "," in context.client_ip:
            context.client_ip = context.client_ip.split(",")[0].strip()
    
    async def _initialize_components(self, context: SessionContext, component_manager):
        """初始化必要的组件"""
        try:
            # 设置组件管理器到上下文
            context.component_manager = component_manager
            
            # 根据配置确定需要初始化的组件
            required_components = ComponentRegistry.get_required_components(self.config)
            
            # 按需初始化组件
            for component_type in required_components:
                component = await component_manager.get_component(component_type, context)
                if component:
                    logger.info(f"组件初始化成功: {component_type.value}")
                else:
                    logger.warning(f"组件初始化失败: {component_type.value}")
            
        except Exception as e:
            logger.error(f"组件初始化出错: {e}")
            raise
    
    async def _check_timeout(self, context: SessionContext, transport: TransportInterface):
        """定期检查连接超时"""
        timeout_seconds = context.config.get("close_connection_no_voice_time", 120)
        check_interval = min(30, timeout_seconds // 4)  # 检查间隔为超时时间的1/4，最多30秒
        
        try:
            while transport.is_connected:
                await asyncio.sleep(check_interval)
                
                if context.is_timeout(timeout_seconds):
                    logger.info(f"连接超时，关闭连接: {context.session_id}")
                    await transport.close()
                    break
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"超时检查出错: {e}")
