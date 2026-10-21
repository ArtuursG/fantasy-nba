"""Local dashboard: one page and a small JSON API on the standard library.

It listens on 127.0.0.1 only and rejects requests whose Host header isn't
this server, so other websites can't read the league data through DNS
rebinding, and cross-site POSTs are refused by an Origin check.
"""

from __future__ import annotations

import json
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fantasy.app import FantasyApp
from fantasy.config import ConfigError
from fantasy.espn.client import EspnError

STATIC = Path(__file__).parent / "static"
MAX_BODY = 8 * 1024 * 1024
STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    # Fonts ship with the app so the dashboard makes no outside requests.
    **{f"fonts/{p.name}": "font/woff2" for p in (STATIC / "fonts").glob("*.woff2")},
    **{f"icons/{p.name}": "image/png" for p in (STATIC / "icons").glob("*.png")},
    "manifest.webmanifest": "application/manifest+json",
}


def make_handler(app: FantasyApp, allowed_hosts: set[str]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "fantasy/0.1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: object) -> None:
            body = json.dumps(payload, allow_nan=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            if self.headers.get("Host", "") not in allowed_hosts:
                self._send(403, b"Unknown host", "text/plain; charset=utf-8")
                return False
            return True

        def do_GET(self) -> None:
            if not self._host_ok():
                return
            url = urlsplit(self.path)
            path = url.path
            if path in ("/", "/index.html"):
                path = "/static/index.html"
            if path.startswith("/static/"):
                name = path.removeprefix("/static/")
                if name not in STATIC_FILES:
                    self._send(404, b"Not found", "text/plain; charset=utf-8")
                    return
                self._send(200, (STATIC / name).read_bytes(), STATIC_FILES[name])
            elif path == "/api/state":
                self._json(200, {"view": app.view(), "demo": app.demo})
            elif path == "/api/settings":
                self._json(200, app.settings())
            elif path == "/api/report":
                query = parse_qs(url.query)
                text = app.report(
                    compact=query.get("compact") == ["1"], brief=query.get("kind") == ["brief"]
                )
                if text is None:
                    self._json(404, {"error": "No snapshot yet: press Refresh first."})
                else:
                    self._send(200, text.encode("utf-8"), "text/plain; charset=utf-8")
            else:
                self._send(404, b"Not found", "text/plain; charset=utf-8")

        def do_POST(self) -> None:
            if not self._host_ok():
                return
            origin = self.headers.get("Origin")
            if origin and origin.split("://", 1)[-1] not in allowed_hosts:
                self._send(403, b"Cross-site request refused", "text/plain; charset=utf-8")
                return
            path = urlsplit(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._send(413, b"Too large", "text/plain; charset=utf-8")
                return
            body = self.rfile.read(length) if length else b""
            try:
                if path == "/api/refresh":
                    app.refresh(log=lambda _msg: None)
                    self._json(200, {"view": app.view(), "demo": app.demo})
                elif path == "/api/trade":
                    form = json.loads(body or b"{}")
                    give = [int(x) for x in form.get("give") or []]
                    get = [int(x) for x in form.get("get") or []]
                    self._json(200, app.evaluate_trade(give, get))
                elif path == "/api/telegram/test":
                    app.send_alert(app.alert(always=True) or "Fantasy report: test message")
                    self._json(200, {"sent": True})
                elif path == "/api/settings":
                    form = json.loads(body or b"{}")
                    if not isinstance(form, dict):
                        raise ConfigError("Settings must be a JSON object")
                    settings = app.update_settings({k: str(v) for k, v in form.items()})
                    self._json(200, {"settings": settings, "view": app.view()})
                else:
                    self._send(404, b"Not found", "text/plain; charset=utf-8")
            except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                self._json(400, {"error": "The request body must be valid JSON"})
            except (ConfigError, EspnError) as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # the page should show it, not hang
                traceback.print_exc()
                self._json(500, {"error": f"Request failed: {exc}"})

    return Handler


def serve(app: FantasyApp, host: str, port: int, open_browser: bool = True) -> None:
    allowed = {f"{host}:{port}", f"localhost:{port}", f"127.0.0.1:{port}"}
    server = ThreadingHTTPServer((host, port), make_handler(app, allowed))
    url = (
        f"http://localhost:{port}/"
        if host in ("127.0.0.1", "0.0.0.0")
        else f"http://{host}:{port}/"
    )
    print(f"Dashboard running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
