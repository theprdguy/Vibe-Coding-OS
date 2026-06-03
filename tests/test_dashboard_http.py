from __future__ import annotations

import json
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import pytest
import yaml

from server.dashboard import BIND_HOST, create_server, make_handler


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _ticket(ticket_id: str, status: str = "todo", **extra: object) -> dict:
    ticket = {
        "id": ticket_id,
        "owner": "CODEX",
        "status": status,
        "priority": "P1",
        "goal": f"{ticket_id} goal\nsecond line",
        "dod": [f"{ticket_id} dod"],
        "files": ["server/dashboard.py"],
    }
    ticket.update(extra)
    return ticket


def _write_queue(root: Path, tickets: list[dict]) -> None:
    _write_yaml(root / "devos" / "tasks" / "QUEUE.yaml", {"version": "3.0", "tickets": tickets})


def _write_archive(root: Path, tickets: list[dict]) -> None:
    _write_yaml(root / "devos" / "tasks" / "ARCHIVE.yaml", {"version": "3.0", "tickets": tickets})


@pytest.fixture
def host_root(tmp_path: Path) -> Path:
    host = tmp_path / "dev-os"
    _write_queue(
        host,
        [
            _ticket("T-KNOWN", "todo", goal="Known goal", dod=["known dod"]),
            _ticket("T-DOING", "doing"),
            _ticket("T-CODE", "code_ready"),
            _ticket("T-PM", "needs_pm"),
            _ticket("T-BLOCK", "blocked"),
            _ticket("T-PARK", "parked"),
        ],
    )
    _write_archive(host, [_ticket("T-DONE", "done")])
    return host


class _Socket:
    def __init__(self, request: bytes) -> None:
        self._request = BytesIO(request)
        self._response = BytesIO()

    def makefile(self, mode: str, buffering: int | None = None):
        if "r" in mode:
            return self._request
        return self._response

    def sendall(self, data: bytes) -> None:
        self._response.write(data)

    def get_response(self) -> bytes:
        return self._response.getvalue()


class _Server:
    server_name = BIND_HOST
    server_port = 0


def _request(host: Path, path: str) -> tuple[int, str, bytes]:
    handler = make_handler(host)
    raw_request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {BIND_HOST}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii")
    sock = _Socket(raw_request)
    handler(sock, (BIND_HOST, 0), _Server())
    header_bytes, body = sock.get_response().split(b"\r\n\r\n", 1)
    header_lines = header_bytes.decode("iso-8859-1").split("\r\n")
    status = int(header_lines[0].split()[1])
    headers = {}
    for line in header_lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.lower()] = value.strip()
    return status, headers.get("content-type", ""), body


def _get_json(host: Path, path: str) -> tuple[int, str, dict]:
    status, content_type, body = _request(host, path)
    return status, content_type, json.loads(body.decode("utf-8"))


def test_get_api_projects_returns_project_list_shape(host_root: Path) -> None:
    status, content_type, data = _get_json(host_root, "/api/projects")

    assert status == 200
    assert content_type.startswith("application/json")
    assert set(data) == {"projects"}
    assert isinstance(data["projects"], list)
    assert data["projects"][0]["name"] == "dev-os"
    assert set(data["projects"][0]) == {"name", "repo_path", "ok", "error", "counts", "total"}
    assert data["projects"][0]["ok"] is True
    assert data["projects"][0]["counts"]["todo"] == 1
    assert data["projects"][0]["counts"]["done"] == 1


def test_get_project_tickets_returns_seven_status_columns(host_root: Path) -> None:
    status, content_type, data = _get_json(host_root, "/api/projects/dev-os/tickets")

    assert status == 200
    assert content_type.startswith("application/json")
    assert data["name"] == "dev-os"
    assert data["ok"] is True
    assert [column["status"] for column in data["columns"]] == [
        "todo",
        "doing",
        "code_ready",
        "needs_pm",
        "blocked",
        "parked",
        "done",
    ]


def test_get_known_ticket_returns_full_ticket(host_root: Path) -> None:
    status, content_type, data = _get_json(host_root, "/api/projects/dev-os/tickets/T-KNOWN")

    assert status == 200
    assert content_type.startswith("application/json")
    assert data["id"] == "T-KNOWN"
    assert data["goal"] == "Known goal"
    assert data["dod"] == ["known dod"]


def test_get_missing_ticket_returns_json_404(host_root: Path) -> None:
    status, content_type, data = _get_json(host_root, "/api/projects/dev-os/tickets/NOPE")

    assert status == 404
    assert content_type.startswith("application/json")
    assert data == {"error": "not found"}


def test_get_unknown_project_returns_json_404(host_root: Path) -> None:
    status, content_type, data = _get_json(host_root, "/api/projects/NOPE/tickets")

    assert status == 404
    assert content_type.startswith("application/json")
    assert data == {"error": "unknown project"}


def test_get_root_serves_html(host_root: Path) -> None:
    status, content_type, body = _request(host_root, "/")

    assert status == 200
    assert content_type.startswith("text/html")
    assert body


def test_unknown_route_returns_json_404(host_root: Path) -> None:
    status, content_type, data = _get_json(host_root, "/does-not-exist")

    assert status == 404
    assert content_type.startswith("application/json")
    assert data == {"error": "not found"}


def test_create_server_binds_localhost_only(monkeypatch: pytest.MonkeyPatch, host_root: Path) -> None:
    captured = {}

    class FakeServer:
        def __init__(self, address: tuple[str, int], handler: object) -> None:
            captured["address"] = address
            captured["handler"] = handler

    monkeypatch.setattr("server.dashboard.ThreadingHTTPServer", FakeServer)

    create_server(host_root, port=8788)

    assert captured["address"] == (BIND_HOST, 8788)


def test_dashboard_cli_help_lists_port_and_no_open() -> None:
    result = subprocess.run(
        [sys.executable, "bin/deos", "dashboard", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert "--port" in result.stdout
    assert "--no-open" in result.stdout
