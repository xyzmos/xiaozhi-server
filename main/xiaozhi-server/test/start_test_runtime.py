import os
import threading
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from wakeword_runtime.config import load_config, setup_logging
from wakeword_runtime.runtime import TestRuntimeApplication, TestRuntimeHttpServer


class RuntimeInstanceLock:
    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._handle = None

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.lock_path, "a+b")
        try:
            if os.name == "nt":
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._handle.seek(0)
            self._handle.truncate()
            self._handle.write(str(os.getpid()).encode("ascii"))
            self._handle.flush()
            return True
        except OSError:
            self.release()
            return False

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if os.name == "nt":
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self._handle.close()
            self._handle = None


def main() -> int:
    test_root = Path(__file__).resolve().parent
    runtime_root = test_root / "wakeword_runtime"
    lock = RuntimeInstanceLock(runtime_root / ".runtime.lock")
    if not lock.acquire():
        print("failed to start test runtime: another test runtime instance is already running")
        print("请先关闭已有的 test runtime 进程，再重新启动。")
        return 1

    config = load_config(runtime_root)
    setup_logging(config.log_file, config.log_level)
    http_server = TestRuntimeHttpServer(test_root)
    app_lock = threading.RLock()
    app = TestRuntimeApplication(config, http_server.event_bridge)

    def restart_runtime() -> None:
        nonlocal app
        with app_lock:
            app.shutdown()
            next_config = load_config(runtime_root)
            setup_logging(next_config.log_file, next_config.log_level)
            next_app = TestRuntimeApplication(next_config, http_server.event_bridge)
            next_app.setup()
            next_app.start()
            app = next_app

    http_server.set_restart_handler(restart_runtime)

    print(f"test runtime started: {http_server.page_url}")
    print(f"wakeword bridge websocket: {http_server.bridge_url}")
    print(f"wakeword enabled: {config.wakeword_enabled}")
    print("press Ctrl+C to stop")

    try:
        with app_lock:
            app.setup()
            app.start()
        http_server.serve_forever()
    except KeyboardInterrupt:
        print("test runtime stopped")
    finally:
        with app_lock:
            app.shutdown()
        http_server.shutdown()
        lock.release()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())