import asyncio
import importlib
import sys
import types
from pathlib import Path


def install_fakes(monkeypatch):
    class Logger:
        def bind(self, **_kwargs):
            return self

        def debug(self, *_args, **_kwargs):
            pass

        def error(self, *_args, **_kwargs):
            pass

        def info(self, *_args, **_kwargs):
            pass

        def warning(self, *_args, **_kwargs):
            pass

    logger_module = types.ModuleType("config.logger")
    logger_module.setup_logging = lambda: Logger()
    config_module = types.ModuleType("config")
    config_module.__path__ = []
    monkeypatch.setitem(sys.modules, "config", config_module)
    monkeypatch.setitem(sys.modules, "config.logger", logger_module)

    psutil_module = types.ModuleType("psutil")
    psutil_module.virtual_memory = lambda: types.SimpleNamespace(total=4 * 1024 * 1024 * 1024)
    monkeypatch.setitem(sys.modules, "psutil", psutil_module)

    class Base:
        pass

    base_module = types.ModuleType("core.providers.asr.base")
    base_module.ASRProviderBase = Base
    monkeypatch.setitem(sys.modules, "core.providers.asr.base", base_module)

    dto_module = types.ModuleType("core.providers.asr.dto.dto")
    dto_module.InterfaceType = types.SimpleNamespace(LOCAL="local")
    monkeypatch.setitem(sys.modules, "core.providers.asr.dto.dto", dto_module)

    utils_module = types.ModuleType("core.providers.asr.utils")
    utils_module.lang_tag_filter = lambda text: {"content": text}
    monkeypatch.setitem(sys.modules, "core.providers.asr.utils", utils_module)

    class FakeAutoModel:
        last_instance = None

        def __init__(self, **_kwargs):
            self.generate_kwargs = None
            FakeAutoModel.last_instance = self

        def generate(self, **kwargs):
            self.generate_kwargs = kwargs
            return [{"text": "你好"}]

    funasr_module = types.ModuleType("funasr")
    funasr_module.AutoModel = FakeAutoModel
    monkeypatch.setitem(sys.modules, "funasr", funasr_module)
    return FakeAutoModel


def test_fun_local_passes_configured_language_to_funasr_generate(tmp_path, monkeypatch):
    server_root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(server_root))
    fake_model = install_fakes(monkeypatch)
    monkeypatch.delitem(sys.modules, "core.providers.asr.fun_local", raising=False)
    module = importlib.import_module("core.providers.asr.fun_local")

    provider = module.ASRProvider(
        {"model_dir": "models/SenseVoiceSmall", "output_dir": str(tmp_path), "language": "zh"},
        delete_audio_file=False,
    )

    artifacts = types.SimpleNamespace(pcm_bytes=b"\0\0", file_path=str(tmp_path / "audio.wav"))
    text, audio_path = asyncio.run(
        provider.speech_to_text([], "session-1", audio_format="pcm", artifacts=artifacts)
    )

    assert text == {"content": "你好"}
    assert audio_path == artifacts.file_path
    assert fake_model.last_instance.generate_kwargs["language"] == "zh"
