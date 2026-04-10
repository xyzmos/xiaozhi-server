import json
import queue
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..bridge import WakewordEventBridge


class TestRuntimeHttpServer:
    def __init__(self, test_root: Path, host: str = "0.0.0.0", port: int = 8006) -> None:
        self.test_root = test_root
        self.host = host
        self.port = port
        self.event_bridge = WakewordEventBridge()
        self._server = self._build_server()

    @property
    def page_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/test_page.html"

    @property
    def events_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/events"

    def serve_forever(self) -> None:
        self._server.serve_forever()

    def shutdown(self) -> None:
        self._server.shutdown()
        self.event_bridge.close()
        self._server.server_close()

    def _build_server(self) -> ThreadingHTTPServer:
        test_root = self.test_root
        event_bridge = self.event_bridge

        class TestRuntimeHandler(SimpleHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(test_root), **kwargs)

            def handle(self) -> None:
                try:
                    super().handle()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def do_GET(self) -> None:
                if self.path == "/events":
                    self._handle_events(event_bridge)
                    return

                if self.path == "/health":
                    body = json.dumps({"status": "ok"}).encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                super().do_GET()

            def log_message(self, format: str, *args) -> None:
                return

            def _handle_events(self, bridge: WakewordEventBridge) -> None:
                client_queue = bridge.add_client()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()

                try:
                    ready_message = bridge.build_ready_message()
                    self.wfile.write(f"data: {ready_message}\n\n".encode("utf-8"))
                    self.wfile.flush()

                    while bridge.is_running:
                        try:
                            message = client_queue.get(timeout=15)
                            if message == "__bridge_closed__":
                                break
                            self.wfile.write(f"data: {message}\n\n".encode("utf-8"))
                        except queue.Empty:
                            if not bridge.is_running:
                                break
                            self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                finally:
                    bridge.remove_client(client_queue)

        server = ThreadingHTTPServer((self.host, self.port), TestRuntimeHandler)
        server.daemon_threads = True
        return server
