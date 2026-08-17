import contextlib
import hashlib
import os
import socket
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pytest

from src.webui.app import create_app

PASSWORD = "testpass"
PASSWORD_HASH = hashlib.sha256(PASSWORD.encode()).hexdigest()

# Some Windows Python builds lack socket.AF_UNIX entirely; the deployment
# target (Linux) always has it. See tests/test_pisugar.py for the same guard.
requires_af_unix = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"), reason="socket.AF_UNIX not available on this platform"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_segment(directory: Path, name: str, size: int = 10, age_seconds: float = 0) -> Path:
    p = directory / name
    p.write_bytes(b"\x00" * size)
    mtime = time.time() - age_seconds
    os.utime(p, (mtime, mtime))
    return p


def make_socket_path() -> str:
    # A short path outside tmp_path's deep pytest nesting -- AF_UNIX paths
    # are limited to ~108 chars on both Linux and Windows.
    return str(Path(tempfile.gettempdir()) / f"pisugar-test-{uuid.uuid4().hex[:8]}.sock")


@contextlib.contextmanager
def fake_pisugar_server(socket_path: str, response: bytes):
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(socket_path)
    srv.listen(1)

    def serve():
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        with conn:
            conn.recv(4096)
            conn.sendall(response)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield
    finally:
        srv.close()
        thread.join(timeout=2)
        try:
            os.unlink(socket_path)
        except FileNotFoundError:
            pass


def make_client(tmp_path):
    app = create_app(
        {
            "recording": {"segment_dir": str(tmp_path)},
            "gui": {"password_hash": PASSWORD_HASH},
            "power": {
                "socket_path": str(tmp_path / "no-such-pisugar.sock"),
                "low_battery_percent": 20,
            },
        }
    )
    app.testing = True
    return app.test_client()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_index_requires_auth(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 401


def test_download_requires_auth(tmp_path):
    make_segment(tmp_path, "20260101_000000_0000.h264")
    client = make_client(tmp_path)
    resp = client.get("/download/20260101_000000_0000.h264")
    assert resp.status_code == 401


def test_delete_requires_auth(tmp_path):
    p = make_segment(tmp_path, "20260101_000000_0000.h264")
    client = make_client(tmp_path)
    resp = client.post("/delete/20260101_000000_0000.h264")
    assert resp.status_code == 401
    assert p.exists()


# ---------------------------------------------------------------------------
# Index listing
# ---------------------------------------------------------------------------

def test_index_lists_segments(tmp_path):
    make_segment(tmp_path, "20260101_000000_0000.h264")
    client = make_client(tmp_path)
    resp = client.get("/", auth=("x", PASSWORD))
    assert resp.status_code == 200
    assert b"20260101_000000_0000.h264" in resp.data


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def test_download_valid_segment(tmp_path):
    make_segment(tmp_path, "20260101_000000_0000.h264", size=42)
    client = make_client(tmp_path)
    resp = client.get("/download/20260101_000000_0000.h264", auth=("x", PASSWORD))
    assert resp.status_code == 200
    assert len(resp.data) == 42


def test_download_nonexistent_file_404(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/download/20260101_000000_0000.h264", auth=("x", PASSWORD))
    assert resp.status_code == 404


def test_download_path_traversal_rejected(tmp_path):
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("do not leak")
    client = make_client(tmp_path)
    for payload in ["..%2f..%2fsecret.txt", "../secret.txt", "%2e%2e%2fsecret.txt"]:
        resp = client.get(f"/download/{payload}", auth=("x", PASSWORD))
        assert resp.status_code == 404


def test_download_rejects_non_segment_filename(tmp_path):
    make_segment(tmp_path, "not-a-segment.h264")
    client = make_client(tmp_path)
    resp = client.get("/download/not-a-segment.h264", auth=("x", PASSWORD))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_removes_file(tmp_path):
    p = make_segment(tmp_path, "20260101_000000_0000.h264")
    client = make_client(tmp_path)
    resp = client.post("/delete/20260101_000000_0000.h264", auth=("x", PASSWORD))
    assert resp.status_code == 302
    assert not p.exists()


def test_delete_path_traversal_rejected(tmp_path):
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("do not leak")
    client = make_client(tmp_path)
    resp = client.post("/delete/../secret.txt", auth=("x", PASSWORD))
    assert resp.status_code == 404
    assert secret.exists()


# ---------------------------------------------------------------------------
# Battery status
# ---------------------------------------------------------------------------

def test_index_shows_battery_unavailable_without_pisugar(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/", auth=("x", PASSWORD))
    assert b"Battery status unavailable" in resp.data


@requires_af_unix
def test_index_shows_battery_percent(tmp_path):
    sock_path = make_socket_path()
    response = b"battery: 55.5\nbattery_charging: false\nbattery_power_plugged: false\n"
    with fake_pisugar_server(sock_path, response):
        app = create_app(
            {
                "recording": {"segment_dir": str(tmp_path)},
                "gui": {"password_hash": PASSWORD_HASH},
                "power": {"socket_path": sock_path, "low_battery_percent": 20},
            }
        )
        app.testing = True
        resp = app.test_client().get("/", auth=("x", PASSWORD))
    assert b"55.5%" in resp.data


@requires_af_unix
def test_index_flags_low_battery(tmp_path):
    sock_path = make_socket_path()
    response = b"battery: 10.0\nbattery_charging: false\nbattery_power_plugged: false\n"
    with fake_pisugar_server(sock_path, response):
        app = create_app(
            {
                "recording": {"segment_dir": str(tmp_path)},
                "gui": {"password_hash": PASSWORD_HASH},
                "power": {"socket_path": sock_path, "low_battery_percent": 20},
            }
        )
        app.testing = True
        resp = app.test_client().get("/", auth=("x", PASSWORD))
    assert b'class="battery-low"' in resp.data


@requires_af_unix
def test_index_does_not_flag_low_battery_while_charging(tmp_path):
    sock_path = make_socket_path()
    response = b"battery: 10.0\nbattery_charging: true\nbattery_power_plugged: true\n"
    with fake_pisugar_server(sock_path, response):
        app = create_app(
            {
                "recording": {"segment_dir": str(tmp_path)},
                "gui": {"password_hash": PASSWORD_HASH},
                "power": {"socket_path": sock_path, "low_battery_percent": 20},
            }
        )
        app.testing = True
        resp = app.test_client().get("/", auth=("x", PASSWORD))
    assert b'class="battery-low"' not in resp.data
    assert b"(charging)" in resp.data
