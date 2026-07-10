import logging

from .framediff import FrameDiff
from .pir import PIRSensor

logger = logging.getLogger(__name__)


class MotionDetector:
    """Coordinates the PIR sensor and frame-diff validator.

    The PIR is the primary trigger. When it fires, FrameDiff validates the
    event against recent frames. on_motion is called only when both agree.

    Lifecycle: call start() once, stop() to clean up. on_motion may be called
    from the GPIO interrupt thread — keep it non-blocking or hand off to a queue.
    """

    def __init__(self, pir: PIRSensor, framediff: FrameDiff, on_motion):
        self._pir = pir
        self._framediff = framediff
        self._on_motion = on_motion

    def start(self) -> None:
        self._framediff.start()
        self._pir.start(callback=self._handle_pir)
        logger.info("Motion detector active")

    def stop(self) -> None:
        self._pir.stop()
        self._framediff.stop()
        logger.info("Motion detector stopped")

    def _handle_pir(self, channel: int) -> None:
        if self._framediff.check():
            logger.info("Motion confirmed (PIR + framediff) on channel %d", channel)
            self._on_motion()
        else:
            logger.debug("PIR fired on channel %d but framediff did not confirm", channel)
