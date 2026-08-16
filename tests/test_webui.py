import hashlib
import os
import time
from pathlib import Path

from src.webui.app import create_app

PASSWORD = "testpass"
PASSWORD_HASH = hashlib.sha256(PASSWORD.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_segment(directory: Path, name: str, size: int = 10, age_seconds: float = 0) -> Path:
    p = directory / name
    p.write_bytes(b"\x00" * size)
    mtime = time.time() - age_seconds
    os.utime(p, (mtime, mtime))
    return p


def make_client(tmp_path):
    app = create_app(
        {
            "recording": {"segment_dir": str(tmp_path)},
            "gui": {"password_hash": PASSWORD_HASH},
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
