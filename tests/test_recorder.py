import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from src.recording.recorder import Recorder


def make_recorder(**kwargs) -> Recorder:
    defaults = dict(segment_dir="/footage", cooldown_seconds=10)
    defaults.update(kwargs)
    return Recorder(**defaults)


@patch("src.recording.recorder.threading.Timer")
@patch("src.recording.recorder.subprocess.Popen")
def test_on_motion_starts_subprocess(MockPopen, MockTimer):
    MockTimer.return_value = MagicMock()
    r = make_recorder()
    r.on_motion()
    MockPopen.assert_called_once()
    assert r._proc is not None


@patch("src.recording.recorder.threading.Timer")
@patch("src.recording.recorder.subprocess.Popen")
def test_second_on_motion_does_not_restart_subprocess(MockPopen, MockTimer):
    MockTimer.return_value = MagicMock()
    r = make_recorder()
    r.on_motion()
    r.on_motion()
    assert MockPopen.call_count == 1


@patch("src.recording.recorder.threading.Timer")
@patch("src.recording.recorder.subprocess.Popen")
def test_second_on_motion_reschedules_cooldown(MockPopen, MockTimer):
    timers = [MagicMock(), MagicMock()]
    MockTimer.side_effect = timers
    r = make_recorder()
    r.on_motion()
    r.on_motion()
    timers[0].cancel.assert_called_once()
    timers[1].start.assert_called_once()


@patch("src.recording.recorder.threading.Timer")
@patch("src.recording.recorder.subprocess.Popen")
def test_cooldown_expiry_stops_recording(MockPopen, MockTimer):
    mock_proc = MagicMock()
    MockPopen.return_value = mock_proc
    MockTimer.return_value = MagicMock()
    r = make_recorder()
    r.on_motion()
    r._on_cooldown_expired()
    mock_proc.terminate.assert_called_once()
    assert r._proc is None


@patch("src.recording.recorder.threading.Timer")
@patch("src.recording.recorder.subprocess.Popen")
def test_stop_cancels_timer_and_terminates_proc(MockPopen, MockTimer):
    mock_proc = MagicMock()
    MockPopen.return_value = mock_proc
    mock_timer = MagicMock()
    MockTimer.return_value = mock_timer
    r = make_recorder()
    r.on_motion()
    r.stop()
    mock_timer.cancel.assert_called()
    mock_proc.terminate.assert_called_once()
    assert r._proc is None


def test_stop_when_idle_is_safe():
    r = make_recorder()
    r.stop()  # must not raise


@patch("src.recording.recorder.threading.Timer")
@patch("src.recording.recorder.subprocess.Popen")
def test_kill_used_when_terminate_times_out(MockPopen, MockTimer):
    mock_proc = MagicMock()
    mock_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd=[], timeout=5), None]
    MockPopen.return_value = mock_proc
    MockTimer.return_value = MagicMock()
    r = make_recorder()
    r.on_motion()
    r.stop()
    mock_proc.kill.assert_called_once()


@patch("src.recording.recorder.threading.Timer")
@patch("src.recording.recorder.subprocess.Popen")
def test_rpicam_command_contains_expected_flags(MockPopen, MockTimer):
    MockTimer.return_value = MagicMock()
    r = make_recorder(segment_dir="/footage", segment_duration=60, width=1920, height=1080, framerate=30)
    r.on_motion()
    cmd = MockPopen.call_args[0][0]
    assert "rpicam-vid" in cmd
    assert "--codec" in cmd and "h264" in cmd
    assert "--inline" in cmd
    assert "--nopreview" in cmd
    assert "--timeout" in cmd and "0" in cmd
    # segment_duration is converted to ms
    assert str(60 * 1000) in cmd


@patch("src.recording.recorder.threading.Timer")
@patch("src.recording.recorder.subprocess.Popen")
def test_output_path_contains_timestamp_and_segment_placeholder(MockPopen, MockTimer):
    MockTimer.return_value = MagicMock()
    r = make_recorder(segment_dir="/footage")
    r.on_motion()
    cmd = MockPopen.call_args[0][0]
    output_idx = cmd.index("--output") + 1
    output = cmd[output_idx]
    assert "footage" in output
    assert "%04d.h264" in output


@patch("src.recording.recorder.threading.Timer")
@patch("src.recording.recorder.subprocess.Popen")
def test_on_start_hook_called_before_subprocess(MockPopen, MockTimer):
    call_order = []
    on_start = lambda: call_order.append("on_start")
    MockPopen.side_effect = lambda *a, **kw: call_order.append("popen") or MagicMock()
    MockTimer.return_value = MagicMock()

    r = make_recorder(on_start=on_start)
    r.on_motion()

    assert call_order == ["on_start", "popen"]


@patch("src.recording.recorder.threading.Timer")
@patch("src.recording.recorder.subprocess.Popen")
def test_on_stop_hook_called_after_subprocess_exits(MockPopen, MockTimer):
    on_stop = MagicMock()
    mock_proc = MagicMock()
    MockPopen.return_value = mock_proc
    MockTimer.return_value = MagicMock()

    r = make_recorder(on_stop=on_stop)
    r.on_motion()
    r.stop()

    mock_proc.terminate.assert_called_once()
    on_stop.assert_called_once()


@patch("src.recording.recorder.threading.Timer")
@patch("src.recording.recorder.subprocess.Popen")
def test_failed_launch_restores_camera_via_on_stop(MockPopen, MockTimer):
    MockPopen.side_effect = OSError("rpicam-vid not found")
    MockTimer.return_value = MagicMock()
    on_stop = MagicMock()

    r = make_recorder(on_stop=on_stop)
    with pytest.raises(OSError):
        r.on_motion()

    on_stop.assert_called_once()
    assert r._proc is None
