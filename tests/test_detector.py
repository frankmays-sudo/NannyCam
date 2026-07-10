from unittest.mock import MagicMock

from src.motion.detector import MotionDetector


def make_detector(framediff_returns: bool = True):
    pir = MagicMock()
    framediff = MagicMock()
    framediff.check.return_value = framediff_returns
    on_motion = MagicMock()
    detector = MotionDetector(pir, framediff, on_motion)
    return detector, pir, framediff, on_motion


def test_pir_plus_framediff_calls_on_motion():
    detector, _, framediff, on_motion = make_detector(framediff_returns=True)
    detector._handle_pir(channel=17)
    on_motion.assert_called_once()


def test_pir_without_framediff_confirmation_no_callback():
    detector, _, framediff, on_motion = make_detector(framediff_returns=False)
    detector._handle_pir(channel=17)
    on_motion.assert_not_called()


def test_start_initialises_framediff_then_pir():
    detector, pir, framediff, _ = make_detector()
    detector.start()
    framediff.start.assert_called_once()
    pir.start.assert_called_once_with(callback=detector._handle_pir)


def test_stop_tears_down_pir_then_framediff():
    detector, pir, framediff, _ = make_detector()
    detector.stop()
    pir.stop.assert_called_once()
    framediff.stop.assert_called_once()
