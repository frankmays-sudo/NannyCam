import signal
from unittest.mock import patch

import pytest

import main as main_module


@pytest.fixture
def mocked_main():
    """Patch every hardware-touching class main.py wires up, plus the signal
    calls that would otherwise register real OS handlers and block forever
    on signal.pause(). No real camera/GPIO/subprocess/socket ever touched.
    """
    with patch.object(main_module, "FrameDiff") as FrameDiff, \
         patch.object(main_module, "Recorder") as Recorder, \
         patch.object(main_module, "PIRSensor") as PIRSensor, \
         patch.object(main_module, "MotionDetector") as MotionDetector, \
         patch.object(main_module, "StorageRing") as StorageRing, \
         patch.object(main_module, "BatteryMonitor") as BatteryMonitor, \
         patch.object(main_module.signal, "signal") as signal_signal, \
         patch.object(main_module.signal, "pause", create=True):
        yield {
            "FrameDiff": FrameDiff,
            "Recorder": Recorder,
            "PIRSensor": PIRSensor,
            "MotionDetector": MotionDetector,
            "StorageRing": StorageRing,
            "BatteryMonitor": BatteryMonitor,
            "signal_signal": signal_signal,
        }


def _get_registered_shutdown(signal_signal_mock):
    """Extract the shutdown callback main() registered for SIGINT/SIGTERM."""
    handlers = {call.args[0]: call.args[1] for call in signal_signal_mock.call_args_list}
    assert signal.SIGINT in handlers
    assert signal.SIGTERM in handlers
    assert handlers[signal.SIGINT] is handlers[signal.SIGTERM]
    return handlers[signal.SIGINT]


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def test_recorder_wired_to_framediff_camera_handoff(mocked_main):
    main_module.main()

    framediff_instance = mocked_main["FrameDiff"].return_value
    recorder_kwargs = mocked_main["Recorder"].call_args.kwargs
    assert recorder_kwargs["on_start"] == framediff_instance.stop
    assert recorder_kwargs["on_stop"] == framediff_instance.start


def test_detector_wired_to_pir_framediff_and_recorder(mocked_main):
    main_module.main()

    pir_instance = mocked_main["PIRSensor"].return_value
    framediff_instance = mocked_main["FrameDiff"].return_value
    recorder_instance = mocked_main["Recorder"].return_value
    detector_kwargs = mocked_main["MotionDetector"].call_args.kwargs
    assert detector_kwargs["pir"] is pir_instance
    assert detector_kwargs["framediff"] is framediff_instance
    assert detector_kwargs["on_motion"] == recorder_instance.on_motion


# ---------------------------------------------------------------------------
# Startup order
# ---------------------------------------------------------------------------

def test_startup_order_is_ring_then_battery_then_detector(mocked_main):
    order = []
    mocked_main["StorageRing"].return_value.start.side_effect = lambda: order.append("ring")
    mocked_main["BatteryMonitor"].return_value.start.side_effect = lambda: order.append("battery")
    mocked_main["MotionDetector"].return_value.start.side_effect = lambda: order.append("detector")

    main_module.main()

    assert order == ["ring", "battery", "detector"]


# ---------------------------------------------------------------------------
# Shutdown order
# ---------------------------------------------------------------------------

def test_shutdown_order_and_exit(mocked_main):
    order = []
    mocked_main["Recorder"].return_value.stop.side_effect = lambda: order.append("recorder")
    mocked_main["MotionDetector"].return_value.stop.side_effect = lambda: order.append("detector")
    mocked_main["StorageRing"].return_value.stop.side_effect = lambda: order.append("ring")
    mocked_main["BatteryMonitor"].return_value.stop.side_effect = lambda: order.append("battery")

    main_module.main()
    shutdown = _get_registered_shutdown(mocked_main["signal_signal"])

    with pytest.raises(SystemExit) as exc_info:
        shutdown(signal.SIGINT, None)

    assert exc_info.value.code == 0
    assert order == ["recorder", "detector", "ring", "battery"]
