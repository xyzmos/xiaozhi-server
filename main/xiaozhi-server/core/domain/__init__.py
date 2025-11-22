"""领域层 - 核心业务逻辑"""

# 服务
from core.domain.services.audio_service import AudioProcessingService, register_audio_service
from core.domain.services.dialogue_service import DialogueService, register_dialogue_service
from core.domain.services.intent_service import IntentService, register_intent_service
from core.domain.services.tts_orchestrator import TTSOrchestrator, register_tts_orchestrator

# 模型
from core.domain.models.session import SessionInfo, SessionState, DialogueMessage, ToolCallInfo
from core.domain.models.config import (
    AudioConfig,
    TTSConfig,
    ASRConfig,
    VADConfig,
    LLMConfig,
    IntentConfig,
    DeviceConfig,
)

__all__ = [
    # 服务
    'AudioProcessingService',
    'DialogueService',
    'IntentService',
    'TTSOrchestrator',

    # 注册函数
    'register_audio_service',
    'register_dialogue_service',
    'register_intent_service',
    'register_tts_orchestrator',

    # 模型
    'SessionInfo',
    'SessionState',
    'DialogueMessage',
    'ToolCallInfo',
    'AudioConfig',
    'TTSConfig',
    'ASRConfig',
    'VADConfig',
    'LLMConfig',
    'IntentConfig',
    'DeviceConfig',
]
