"""Loopback-only HTTP transport and static assets for the interactive UI."""

from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import RLock

from .interactive_ui import ComparisonApp

MAX_BODY_BYTES = 32_768
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


def make_server(app: ComparisonApp, *, port: int = 8000) -> ThreadingHTTPServer:
    """Create a local server; the lock serializes session mutations and GPU use."""
    lock = RLock()

    class Handler(BaseHTTPRequestHandler):
        server: ThreadingHTTPServer

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, format, *args):
            pass  # Player inputs and session tokens do not belong in logs.

        def _send(
            self,
            status,
            data,
            content_type="application/json; charset=utf-8",
            cookie=None,
        ):
            body = (
                data
                if isinstance(data, bytes)
                else json.dumps(data, ensure_ascii=False).encode()
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            if cookie:
                self.send_header(
                    "Set-Cookie",
                    f"quest_session={cookie}; HttpOnly; SameSite=Strict; Path=/",
                )
            self.end_headers()
            self.wfile.write(body)

        def _local_request(self):
            allowed = {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            host = self.headers.get("Host")
            origin = self.headers.get("Origin")
            if host not in allowed or (origin and origin != f"http://{host}"):
                self._send(403, {"error": "Local same-origin requests only"})
                return False
            return True

        def _session(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except CookieError:
                return None
            value = cookie.get("quest_session")
            session_id = value.value if value else None
            return session_id if session_id in app.sessions else None

        def do_GET(self):
            if not self._local_request():
                return
            if self.path == "/favicon.ico":
                self._send(204, b"")
            elif self.path in ASSETS:
                name, content_type = ASSETS[self.path]
                self._send(
                    200, (Path(__file__).parent / name).read_bytes(), content_type
                )
            elif self.path == "/api/session":
                with lock:
                    session_id = self._session()
                    if session_id is None:
                        if len(app.sessions) >= 128:
                            self._send(
                                503,
                                {
                                    "error": "Session limit reached; restart the local server"
                                },
                            )
                            return
                        session_id = app.new_session()
                    self._send(200, app.describe(session_id), cookie=session_id)
            else:
                self._send(404, {"error": "Not found"})

        def do_POST(self):
            if not self._local_request():
                return
            if self.path not in ("/api/compare", "/api/turn"):
                self._send(404, {"error": "Not found"})
                return
            if self.headers.get_content_type() != "application/json":
                self._send(415, {"error": "Expected application/json"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY_BYTES or self.headers.get(
                    "Transfer-Encoding"
                ):
                    self._send(413, {"error": "Request body must be 1–32768 bytes"})
                    return
                payload = json.loads(self.rfile.read(length))
                with lock:
                    session_id = self._session()
                    if session_id is None:
                        self._send(409, {"error": "Session expired; reload the page"})
                        return
                    action = app.compare if self.path == "/api/compare" else app.turn
                    self._send(200, action(session_id, payload))
            except (ValueError, UnicodeError) as error:
                self._send(400, {"error": str(error)})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
