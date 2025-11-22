"""领域服务注册 - 将所有服务注册到事件总线"""

from typing import TYPE_CHECKING, Dict, Any

from config.logger import setup_logging
from core.domain.services.audio_service import AudioProcessingService, register_audio_service
from core.domain.services.dialogue_service import DialogueService, register_dialogue_service
from core.domain.services.intent_service import IntentService, register_intent_service
from core.domain.services.tts_orchestrator import TTSOrchestrator, register_tts_orchestrator

if TYPE_CHECKING:
    from core.infrastructure.di.container import DIContainer
    from core.infrastructure.event.event_bus import EventBus


class DomainServiceRegistry:
    """领域服务注册器"""

    def __init__(self, container: 'DIContainer', event_bus: 'EventBus'):
        self.container = container
        self.event_bus = event_bus
        self.logger = setup_logging()
        self._services: Dict[str, Any] = {}

    def register_all(self) -> Dict[str, Any]:
        """注册所有领域服务"""
        self.logger.info("开始注册领域服务...")

        # 注册音频处理服务
        self._services['audio_service'] = register_audio_service(
            self.container,
            self.event_bus
        )
        self.logger.debug("已注册: AudioProcessingService")

        # 注册对话服务
        self._services['dialogue_service'] = register_dialogue_service(
            self.container,
            self.event_bus
        )
        self.logger.debug("已注册: DialogueService")

        # 注册意图服务
        self._services['intent_service'] = register_intent_service(
            self.container,
            self.event_bus
        )
        self.logger.debug("已注册: IntentService")

        # 注册 TTS 编排服务
        self._services['tts_orchestrator'] = register_tts_orchestrator(
            self.container,
            self.event_bus
        )
        self.logger.debug("已注册: TTSOrchestrator")

        # 将服务注册到容器
        self._register_to_container()

        self.logger.info(f"领域服务注册完成，共 {len(self._services)} 个服务")
        return self._services

    def _register_to_container(self):
        """将服务注册到 DI 容器"""
        from core.infrastructure.di.container import ServiceScope

        for name, service in self._services.items():
            self.container.register(
                name,
                instance=service,
                scope=ServiceScope.SINGLETON
            )

    def get_service(self, name: str) -> Any:
        """获取服务实例"""
        return self._services.get(name)


def register_domain_services(container: 'DIContainer', event_bus: 'EventBus') -> Dict[str, Any]:
    """注册所有领域服务的便捷函数"""
    registry = DomainServiceRegistry(container, event_bus)
    return registry.register_all()
