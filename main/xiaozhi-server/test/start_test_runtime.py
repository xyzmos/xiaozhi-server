from pathlib import Path

from wakeword_runtime.config import load_config, setup_logging
from wakeword_runtime.runtime import TestRuntimeApplication, TestRuntimeHttpServer


def main() -> int:
    test_root = Path(__file__).resolve().parent
    config = load_config(test_root / "wakeword_runtime")
    setup_logging(config.log_file, config.log_level)
    http_server = TestRuntimeHttpServer(test_root)
    app = TestRuntimeApplication(config, http_server)

    print(f"test runtime started: {http_server.page_url}")
    print(f"wakeword events endpoint: {http_server.events_url}")
    print(f"wakeword enabled: {config.wakeword_enabled}")
    print("press Ctrl+C to stop")

    try:
        app.setup()
        app.start()
        http_server.serve_forever()
    except KeyboardInterrupt:
        print("test runtime stopped")
    finally:
        app.shutdown()
        http_server.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())