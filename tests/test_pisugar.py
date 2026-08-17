import contextlib
import os
import socket
import tempfile
import threading
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from src.power.pisugar import BatteryMonitor, BatteryStatus, read_battery_status

# Some Windows Python builds lack socket.AF_UNIX entirely; the deployment
# target (Linux) always has it. Tests that need a real fake UDS server can't
# run without it -- read_battery_status()'s graceful-degradation path
# (returning None) is still exercised on those platforms via the
# "unreachable socket" test below, which needs no working AF_UNIX socket.
requires_af_unix = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"), reason="socket.AF_UNIX not available on this platform"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# read_battery_status
# ---------------------------------------------------------------------------

@requires_af_unix
def test_read_battery_status_parses_response():
    sock_path = make_socket_path()
    response = b"battery: 73.25\nbattery_charging: true\nbattery_power_plugged: true\n"
    with fake_pisugar_server(sock_path, response):
        status = read_battery_status(sock_path)
    assert status == BatteryStatus(percent=73.25, charging=True, power_plugged=True)


def test_read_battery_status_unreachable_socket_returns_none(tmp_path):
    assert read_battery_status(str(tmp_path / "no-such.sock")) is None


@requires_af_unix
def test_read_battery_status_malformed_response_returns_none():
    sock_path = make_socket_path()
    with fake_pisugar_server(sock_path, b"garbage\n\n\n"):
        status = read_battery_status(sock_path)
    assert status is None


# ---------------------------------------------------------------------------
# BatteryMonitor — threshold-crossing logic, mocking read_battery_status
# ---------------------------------------------------------------------------

@patch("src.power.pisugar.read_battery_status")
def test_warns_once_on_crossing_below_threshold(mock_read):
    mock_read.return_value = BatteryStatus(percent=15.0, charging=False, power_plugged=False)
    monitor = BatteryMonitor("irrelevant.sock", low_battery_percent=20, poll_interval=3600)
    with patch("src.power.pisugar.logger") as mock_logger:
        monitor._check_once()
        monitor._check_once()  # still low -- must not warn again
    assert mock_logger.warning.call_count == 1


@patch("src.power.pisugar.read_battery_status")
def test_does_not_warn_above_threshold(mock_read):
    mock_read.return_value = BatteryStatus(percent=80.0, charging=False, power_plugged=False)
    monitor = BatteryMonitor("irrelevant.sock", low_battery_percent=20, poll_interval=3600)
    with patch("src.power.pisugar.logger") as mock_logger:
        monitor._check_once()
    mock_logger.warning.assert_not_called()


@patch("src.power.pisugar.read_battery_status")
def test_does_not_warn_when_plugged_in_even_if_low(mock_read):
    mock_read.return_value = BatteryStatus(percent=5.0, charging=True, power_plugged=True)
    monitor = BatteryMonitor("irrelevant.sock", low_battery_percent=20, poll_interval=3600)
    with patch("src.power.pisugar.logger") as mock_logger:
        monitor._check_once()
    mock_logger.warning.assert_not_called()


@patch("src.power.pisugar.read_battery_status")
def test_warns_again_after_recovering_and_dropping_again(mock_read):
    monitor = BatteryMonitor("irrelevant.sock", low_battery_percent=20, poll_interval=3600)
    with patch("src.power.pisugar.logger") as mock_logger:
        mock_read.return_value = BatteryStatus(percent=15.0, charging=False, power_plugged=False)
        monitor._check_once()
        mock_read.return_value = BatteryStatus(percent=50.0, charging=False, power_plugged=False)
        monitor._check_once()
        mock_read.return_value = BatteryStatus(percent=10.0, charging=False, power_plugged=False)
        monitor._check_once()
    assert mock_logger.warning.call_count == 2


@patch("src.power.pisugar.read_battery_status")
def test_check_once_handles_unreachable_pisugar(mock_read):
    mock_read.return_value = None
    monitor = BatteryMonitor("irrelevant.sock", low_battery_percent=20, poll_interval=3600)
    monitor._check_once()  # must not raise


# ---------------------------------------------------------------------------
# BatteryMonitor — lifecycle
# ---------------------------------------------------------------------------

def test_stop_wakes_sleeping_thread():
    monitor = BatteryMonitor("irrelevant.sock", low_battery_percent=20, poll_interval=3600)
    monitor.start()
    thread = monitor._thread
    assert thread.is_alive()
    monitor.stop()
    assert not thread.is_alive()


def test_stop_is_idempotent():
    monitor = BatteryMonitor("irrelevant.sock", low_battery_percent=20, poll_interval=3600)
    monitor.start()
    monitor.stop()
    monitor.stop()  # must not raise
