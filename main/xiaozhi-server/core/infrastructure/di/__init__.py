"""依赖注入模块"""

from core.infrastructure.di.container import DIContainer, ServiceDescriptor, ServiceScope
from core.infrastructure.di.lifecycle import LifecycleManager, LifecycleState

__all__ = [
    'DIContainer',
    'ServiceScope',
    'ServiceDescriptor',
    'LifecycleManager',
    'LifecycleState',
]
