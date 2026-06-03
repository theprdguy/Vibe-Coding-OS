"""Local read-only HTTP dashboard for deos tickets."""
from __future__ import annotations

import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from server.dashboard_data import (
    list_dashboard_projects,
    load_project_board,
    load_ticket_detail,
)

BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
STATIC_DIR = Path(__file__).resolve().parent / "dashboard_static"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
}


class DashboardRequestHandler(BaseHTTPRequestHandler):
    """Serve read-only dashboard API and static files."""

    host_root = Path(".")
    static_dir = STATIC_DIR
    server_version = "deosBoard/0.1"

    def do_GET(self) -> None:
        path = unquote(urlsplit(self.path).path)
        if path == "/":
            self._serve_static_file(self.static_dir / "index.html")
            return
        if path.startswith("/static/"):
            self._serve_static_path(path.removeprefix("/static/"))
            return
        if path == "/api/projects":
            self._send_json(200, {"projects": list_dashboard_projects(self.host_root)})
            return

        segments = [segment for segment in path.split("/") if segment]
        if len(segments) == 4 and segments[:2] == ["api", "projects"] and segments[3] == "tickets":
            self._serve_project_board(segments[2])
            return
        if len(segments) == 5 and segments[:2] == ["api", "projects"] and segments[3] == "tickets":
            self._serve_ticket_detail(segments[2], segments[4])
            return

        self._send_json(404, {"error": "not found"})

    def do_HEAD(self) -> None:
        self._method_not_allowed()

    def do_POST(self) -> None:
        self._method_not_allowed()

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _serve_project_board(self, project_name: str) -> None:
        board = load_project_board(self.host_root, project_name)
        if board is None:
            self._send_json(404, {"error": "unknown project"})
            return
        self._send_json(200, board)

    def _serve_ticket_detail(self, project_name: str, ticket_id: str) -> None:
        if not self._project_exists(project_name):
            self._send_json(404, {"error": "unknown project"})
            return
        ticket = load_ticket_detail(self.host_root, project_name, ticket_id)
        if ticket is None:
            self._send_json(404, {"error": "not found"})
            return
        self._send_json(200, ticket)

    def _project_exists(self, project_name: str) -> bool:
        return any(project.get("name") == project_name for project in list_dashboard_projects(self.host_root))

    def _serve_static_path(self, relative_url_path: str) -> None:
        relative_path = Path(relative_url_path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            self._send_json(404, {"error": "not found"})
            return
        self._serve_static_file(self.static_dir / relative_path)

    def _serve_static_file(self, path: Path) -> None:
        try:
            root = self.static_dir.resolve()
            resolved = path.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            self._send_json(404, {"error": "not found"})
            return
        if not resolved.is_file():
            self._send_json(404, {"error": "not found"})
            return
        body = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _CONTENT_TYPES.get(resolved.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _method_not_allowed(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        body = json.dumps({"error": "method not allowed"}).encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_handler(host_root: Path, static_dir: Path = STATIC_DIR) -> type[DashboardRequestHandler]:
    class BoundDashboardRequestHandler(DashboardRequestHandler):
        pass

    BoundDashboardRequestHandler.host_root = Path(host_root)
    BoundDashboardRequestHandler.static_dir = Path(static_dir)
    return BoundDashboardRequestHandler


def create_server(host_root: Path, *, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """Create a localhost-only dashboard server without starting it."""
    return ThreadingHTTPServer((BIND_HOST, int(port)), make_handler(Path(host_root)))


def serve(host_root: Path, *, port: int = DEFAULT_PORT, open_browser: bool = True) -> int:
    """Serve the dashboard until interrupted."""
    try:
        httpd = create_server(host_root, port=port)
    except OSError as exc:
        print(
            f"error: cannot bind {BIND_HOST}:{port}: {exc}. Try --port <port>.",
            file=sys.stderr,
        )
        return 1

    address, bound_port = httpd.server_address
    url = f"http://{address}:{bound_port}/"
    print(f"deos dashboard serving {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\ndeos dashboard stopped.")
    finally:
        httpd.server_close()
    return 0
