import logging
import threading
from collections import deque
from typing import Protocol

import numpy as np

from ..config import RuntimeConfig

logger = logging.getLogger(__name__)


class AudioListener(Protocol):
    def on_audio_data(self, audio_data: np.ndarray) -> None:
        ...


class MicrophoneListener:
    _MAX_QUEUE_SIZE = 10

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self._stream = None
        self._running = False
        self._listeners: list[AudioListener] = []
        self._sample_rate = self.config.audio.sample_rate
        self._channels = self.config.audio.channels
        self._device = self.config.audio.input_device
        self._block_duration_ms = 100
        self._block_size = int(self._sample_rate * (self._block_duration_ms / 1000))
        self._audio_queue: deque = deque(maxlen=self._MAX_QUEUE_SIZE)
        self._queue_event = threading.Event()
        self._consumer_thread = None

    def add_audio_listener(self, listener: AudioListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_audio_listener(self, listener: AudioListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def start(self) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency: sounddevice. Install runtime dependencies before starting microphone listener."
            ) from exc

        self._running = True
        self._audio_queue.clear()
        self._consumer_thread = threading.Thread(
            target=self._consume_loop, daemon=True, name="mic-consumer"
        )
        self._consumer_thread.start()

        self._stream = sd.InputStream(
            device=self._device,
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="int16",
            blocksize=self._block_size,
            callback=self._input_callback,
            latency="low",
        )
        self._stream.start()

        logger.info("microphone listener started")
        logger.info("microphone sample rate: %s", self._sample_rate)
        logger.info("microphone channels: %s", self._channels)
        logger.info("microphone device: %s", self._device if self._device is not None else "default")
        logger.info("microphone block size: %s", self._block_size)

    def stop(self) -> None:
        if not self._running and self._stream is None:
            return

        self._running = False
        self._queue_event.set()
        if self._consumer_thread is not None:
            self._consumer_thread.join(timeout=2)
            self._consumer_thread = None
        if self._stream is not None:
            try:
                self._stream.stop()
            finally:
                self._stream.close()
                self._stream = None
        logger.info("microphone listener stopped")

    def _input_callback(self, indata, frames, time_info, status) -> None:
        _ = frames, time_info
        if status:
            logger.warning("microphone status: %s", status)

        audio = np.copy(indata)
        if audio.ndim > 1:
            audio = audio[:, 0]
        else:
            audio = audio.reshape(-1)

        self._audio_queue.append(audio)
        self._queue_event.set()

    def _consume_loop(self) -> None:
        while self._running:
            self._queue_event.wait(timeout=0.5)
            self._queue_event.clear()
            while self._audio_queue:
                audio = self._audio_queue.popleft()
                for listener in list(self._listeners):
                    try:
                        listener.on_audio_data(audio)
                    except Exception:
                        logger.exception("audio listener callback failed")
