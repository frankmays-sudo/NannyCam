import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.storage.ring import StorageRing, enforce_quota


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_segment(directory: Path, name: str, size: int, age_seconds: float) -> Path:
    p = directory / name
    p.write_bytes(b"\x00" * size)
    mtime = time.time() - age_seconds
    os.utime(p, (mtime, mtime))
    return p


# ---------------------------------------------------------------------------
# enforce_quota — pure function tests using real temp dirs
# ---------------------------------------------------------------------------

def test_nonexistent_dir_returns_empty(tmp_path):
    assert enforce_quota(tmp_path / "missing", 1000) == []


def test_empty_dir_returns_empty(tmp_path):
    assert enforce_quota(tmp_path, 1000) == []


def test_under_quota_no_deletion(tmp_path):
    make_segment(tmp_path, "a.h264", 100, age_seconds=10)
    make_segment(tmp_path, "b.h264", 100, age_seconds=5)
    assert enforce_quota(tmp_path, 1000) == []


def test_single_file_never_deleted_even_when_over_quota(tmp_path):
    make_segment(tmp_path, "only.h264", 500, age_seconds=5)
    assert enforce_quota(tmp_path, 100) == []


def test_deletes_oldest_when_over_quota(tmp_path):
    old = make_segment(tmp_path, "old.h264", 600, age_seconds=20)
    new = make_segment(tmp_path, "new.h264", 600, age_seconds=5)
    deleted = enforce_quota(tmp_path, 1000)
    assert old in deleted
    assert new not in deleted
    assert not old.exists()
    assert new.exists()


def test_newest_file_is_always_protected(tmp_path):
    make_segment(tmp_path, "a.h264", 400, age_seconds=30)
    make_segment(tmp_path, "b.h264", 400, age_seconds=20)
    newest = make_segment(tmp_path, "newest.h264", 400, age_seconds=1)
    # total=1200, quota=500 — two files must go but newest is protected
    deleted = enforce_quota(tmp_path, 500)
    assert newest not in deleted
    assert newest.exists()


def test_deletes_multiple_files_until_under_quota(tmp_path):
    a = make_segment(tmp_path, "a.h264", 300, age_seconds=30)
    b = make_segment(tmp_path, "b.h264", 300, age_seconds=20)
    c = make_segment(tmp_path, "c.h264", 300, age_seconds=10)  # protected as newest
    # total=900, quota=400 → delete a and b
    deleted = enforce_quota(tmp_path, 400)
    assert a in deleted
    assert b in deleted
    assert c not in deleted
    assert c.exists()


def test_non_h264_files_ignored(tmp_path):
    make_segment(tmp_path, "a.h264", 100, age_seconds=10)
    (tmp_path / "thumb.jpg").write_bytes(b"\x00" * 900)
    # Only 100 bytes of .h264, quota=500 — nothing should be deleted
    assert enforce_quota(tmp_path, 500) == []


def test_returns_deleted_paths(tmp_path):
    old = make_segment(tmp_path, "old.h264", 600, age_seconds=20)
    make_segment(tmp_path, "new.h264", 600, age_seconds=5)
    deleted = enforce_quota(tmp_path, 1000)
    assert deleted == [old]


def test_missing_file_during_unlink_does_not_raise(tmp_path, monkeypatch):
    make_segment(tmp_path, "a.h264", 600, age_seconds=20)
    make_segment(tmp_path, "b.h264", 600, age_seconds=5)

    original = Path.unlink

    def unlink_that_raises(self, missing_ok=False):
        raise FileNotFoundError

    monkeypatch.setattr(Path, "unlink", unlink_that_raises)
    deleted = enforce_quota(tmp_path, 500)  # must not raise
    assert deleted == []


# ---------------------------------------------------------------------------
# StorageRing — lifecycle and integration
# ---------------------------------------------------------------------------

@patch("src.storage.ring.enforce_quota")
def test_enforce_quota_called_immediately_on_start(mock_enforce, tmp_path):
    called = threading.Event()
    mock_enforce.side_effect = lambda *_: called.set()

    ring = StorageRing(tmp_path, quota_bytes=1000, poll_interval=3600)
    ring.start()
    assert called.wait(timeout=2), "enforce_quota was not called within 2 s"
    ring.stop()
    mock_enforce.assert_called_with(tmp_path, 1000)


def test_stop_wakes_sleeping_thread(tmp_path):
    ring = StorageRing(tmp_path, quota_bytes=1000, poll_interval=3600)
    ring.start()
    thread = ring._thread
    assert thread.is_alive()
    ring.stop()
    assert not thread.is_alive()


def test_stop_is_idempotent(tmp_path):
    ring = StorageRing(tmp_path, quota_bytes=1000, poll_interval=3600)
    ring.start()
    ring.stop()
    ring.stop()  # must not raise
