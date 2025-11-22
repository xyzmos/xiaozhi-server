"""配置模型"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AudioConfig:
    """音频配置"""
    format: str = "opus"
    sample_rate: int = 16000
    channels: int = 1
    bit_depth: int = 16


@dataclass
class TTSConfig:
    """TTS 配置"""
    provider: str = "edge"
    voice: str = "zh-CN-XiaoxiaoNeural"
    speed: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ASRConfig:
    """ASR 配置"""
    provider: str = "funasr"
    language: str = "zh"
    enable_punctuation: bool = True
    enable_itn: bool = True
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VADConfig:
    """VAD 配置"""
    provider: str = "silero"
    threshold: float = 0.5
    min_silence_duration: int = 500  # ms
    speech_pad_ms: int = 30
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: str = "openai"
    model: str = "gpt-3.5-turbo"
    temperature: float = 0.7
    max_tokens: int = 2048
    system_prompt: str = ""
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IntentConfig:
    """意图识别配置"""
    type: str = "nointent"  # nointent, function_call, intent_llm
    provider: str = ""
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceConfig:
    """设备配置"""
    device_id: str
    name: str = ""
    wakeup_words: List[str] = field(default_factory=list)
    cmd_exit: List[str] = field(default_factory=list)
    greeting: str = ""
    close_connection_no_voice_time: int = 120
    max_output_size: int = 0

    audio: AudioConfig = field(default_factory=AudioConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    asr: ASRConfig = field(default_factory=ASRConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    intent: IntentConfig = field(default_factory=IntentConfig)

    extra_params: Dict[str, Any] = field(default_factory=dict)
