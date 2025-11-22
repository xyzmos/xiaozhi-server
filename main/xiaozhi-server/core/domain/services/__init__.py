"""领域服务"""

from core.domain.services.audio_service import AudioProcessingService, register_audio_service
from core.domain.services.dialogue_service import DialogueService, register_dialogue_service
from core.domain.services.intent_service import IntentService, register_intent_service
from core.domain.services.tts_orchestrator import TTSOrchestrator, register_tts_orchestrator
from core.domain.services.service_registry import DomainServiceRegistry, register_domain_services

__all__ = [
    # 服务类
    'AudioProcessingService',
    'DialogueService',
    'IntentService',
    'TTSOrchestrator',

    # 注册函数
    'register_audio_service',
    'register_dialogue_service',
    'register_intent_service',
    'register_tts_orchestrator',

    # 注册器
    'DomainServiceRegistry',
    'register_domain_services',
]
