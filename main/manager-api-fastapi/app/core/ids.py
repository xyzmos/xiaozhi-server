from __future__ import annotations

import os
import socket
import threading
import time


class SnowflakeIdGenerator:
    """MyBatis-Plus compatible 41/5/5/12-bit Snowflake identifier generator."""

    EPOCH = 1288834974657
    SEQUENCE_BITS = 12
    WORKER_BITS = 5
    DATACENTER_BITS = 5
    MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1
    WORKER_SHIFT = SEQUENCE_BITS
    DATACENTER_SHIFT = SEQUENCE_BITS + WORKER_BITS
    TIMESTAMP_SHIFT = SEQUENCE_BITS + WORKER_BITS + DATACENTER_BITS

    def __init__(self, worker_id: int | None = None, datacenter_id: int | None = None):
        host_hash = sum(socket.gethostname().encode("utf-8"))
        self.worker_id = worker_id if worker_id is not None else (host_hash ^ os.getpid()) & 31
        self.datacenter_id = datacenter_id if datacenter_id is not None else host_hash & 31
        if not 0 <= self.worker_id <= 31 or not 0 <= self.datacenter_id <= 31:
            raise ValueError("worker_id and datacenter_id must be in [0, 31]")
        self._sequence = 0
        self._last_timestamp = -1
        self._lock = threading.Lock()

    @staticmethod
    def _milliseconds() -> int:
        return time.time_ns() // 1_000_000

    def next_id(self) -> int:
        with self._lock:
            timestamp = self._milliseconds()
            if timestamp < self._last_timestamp:
                raise RuntimeError("clock moved backwards; refusing to generate a duplicate Snowflake ID")
            if timestamp == self._last_timestamp:
                self._sequence = (self._sequence + 1) & self.MAX_SEQUENCE
                if self._sequence == 0:
                    while timestamp <= self._last_timestamp:
                        timestamp = self._milliseconds()
            else:
                self._sequence = 0
            self._last_timestamp = timestamp
            return (
                ((timestamp - self.EPOCH) << self.TIMESTAMP_SHIFT)
                | (self.datacenter_id << self.DATACENTER_SHIFT)
                | (self.worker_id << self.WORKER_SHIFT)
                | self._sequence
            )


snowflake = SnowflakeIdGenerator()
