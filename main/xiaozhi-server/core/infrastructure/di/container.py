"""依赖注入容器"""

from typing import Any, Callable, Dict, Optional, Type

from config.logger import setup_logging


class ServiceScope(str):
    """服务作用域"""
    SINGLETON = "singleton"  # 全局单例
    SESSION = "session"      # 会话级单例
    TRANSIENT = "transient"  # 每次创建新实例


class ServiceDescriptor:
    """服务描述符"""

    def __init__(
        self,
        service_type: Type,
        implementation: Optional[Type] = None,
        factory: Optional[Callable] = None,
        scope: ServiceScope = ServiceScope.SINGLETON,
        instance: Optional[Any] = None,
    ):
        self.service_type = service_type
        self.implementation = implementation
        self.factory = factory
        self.scope = scope
        self.instance = instance

        if not implementation and not factory and instance is None:
            raise ValueError("必须提供 implementation, factory 或 instance 之一")


class DIContainer:
    """依赖注入容器 - 管理服务的注册和解析"""

    def __init__(self):
        self._services: Dict[str, ServiceDescriptor] = {}
        self._session_services: Dict[str, Dict[str, Any]] = {}  # session_id -> {service_name -> instance}
        self.logger = setup_logging()

    def register(
        self,
        name: str,
        service_type: Optional[Type] = None,
        implementation: Optional[Type] = None,
        factory: Optional[Callable] = None,
        scope: ServiceScope = ServiceScope.SINGLETON,
        instance: Optional[Any] = None,
    ):
        """注册服务

        Args:
            name: 服务名称
            service_type: 服务类型（接口）
            implementation: 实现类型
            factory: 工厂函数
            scope: 作用域
            instance: 实例（仅用于单例）
        """
        if instance is not None:
            descriptor = ServiceDescriptor(
                service_type=service_type or type(instance),
                instance=instance,
                scope=ServiceScope.SINGLETON,
            )
        elif factory:
            descriptor = ServiceDescriptor(
                service_type=service_type,
                factory=factory,
                scope=scope,
            )
        elif implementation:
            descriptor = ServiceDescriptor(
                service_type=service_type or implementation,
                implementation=implementation,
                scope=scope,
            )
        else:
            raise ValueError("必须提供 implementation, factory 或 instance")

        self._services[name] = descriptor
        self.logger.debug(f"注册服务: {name} (作用域: {scope})")

    def register_singleton(self, name: str, instance: Any):
        """注册单例服务"""
        self.register(name, instance=instance, scope=ServiceScope.SINGLETON)

    def register_factory(
        self,
        name: str,
        factory: Callable,
        scope: ServiceScope = ServiceScope.TRANSIENT,
    ):
        """注册工厂服务"""
        self.register(name, factory=factory, scope=scope)

    def resolve(self, name: str, session_id: Optional[str] = None, **kwargs) -> Any:
        """解析服务

        Args:
            name: 服务名称
            session_id: 会话ID（用于会话级服务）
            **kwargs: 传递给工厂函数的参数

        Returns:
            服务实例
        """
        # 首先检查会话级缓存中是否有直接注册的服务（如 session_context）
        if session_id and session_id in self._session_services:
            if name in self._session_services[session_id]:
                return self._session_services[session_id][name]

        if name not in self._services:
            raise ValueError(f"服务 '{name}' 未注册")

        descriptor = self._services[name]

        # 单例作用域
        if descriptor.scope == ServiceScope.SINGLETON:
            if descriptor.instance is not None:
                return descriptor.instance

            # 创建单例实例
            instance = self._create_instance(descriptor, **kwargs)
            descriptor.instance = instance
            return instance

        # 会话作用域
        if descriptor.scope == ServiceScope.SESSION:
            if not session_id:
                raise ValueError(f"服务 '{name}' 需要 session_id")

            # 检查会话级缓存
            if session_id not in self._session_services:
                self._session_services[session_id] = {}

            if name in self._session_services[session_id]:
                return self._session_services[session_id][name]

            # 创建会话级实例
            instance = self._create_instance(descriptor, session_id=session_id, **kwargs)
            self._session_services[session_id][name] = instance
            return instance

        # 瞬态作用域 - 每次创建新实例
        return self._create_instance(descriptor, session_id=session_id, **kwargs)

    def _create_instance(self, descriptor: ServiceDescriptor, **kwargs) -> Any:
        """创建服务实例"""
        try:
            if descriptor.factory:
                # 使用工厂函数创建
                return descriptor.factory(self, **kwargs)
            elif descriptor.implementation:
                # 使用构造函数创建
                return descriptor.implementation(**kwargs)
            else:
                raise ValueError("无法创建实例：缺少 factory 或 implementation")
        except Exception as e:
            self.logger.error(f"创建服务实例失败: {e}", exc_info=True)
            raise

    def cleanup_session(self, session_id: str):
        """清理会话级服务

        Args:
            session_id: 会话ID
        """
        if session_id in self._session_services:
            count = len(self._session_services[session_id])
            del self._session_services[session_id]
            self.logger.debug(f"清理会话 {session_id} 的 {count} 个服务")

    def has_service(self, name: str) -> bool:
        """检查服务是否已注册"""
        return name in self._services

    def get_service_names(self) -> list:
        """获取所有已注册的服务名称"""
        return list(self._services.keys())

    def register_session_context(self, session_id: str, context: Any):
        """注册会话上下文

        Args:
            session_id: 会话ID
            context: 会话上下文实例
        """
        if session_id not in self._session_services:
            self._session_services[session_id] = {}

        self._session_services[session_id]['session_context'] = context
        self.logger.debug(f"注册会话上下文: {session_id}")

    def clear(self):
        """清空所有服务注册"""
        self._services.clear()
        self._session_services.clear()
        self.logger.info("容器已清空")
