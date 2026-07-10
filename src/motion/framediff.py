import logging
import threading
import time

import numpy as np

logger = logging.getLogger(__name__)

_PIXEL_DELTA = 25  # per-pixel luma change (0-255) required to count as "different"


def detect_motion(
    prev: np.ndarray,
    curr: np.ndarray,
    threshold: float,
    pixel_delta: int = _PIXEL_DELTA,
) -> bool:
    """Return True if the fraction of changed pixels exceeds threshold.

    Both frames must be 2-D grayscale uint8 arrays of the same shape.
    """
    diff = np.abs(curr.astype(np.int16) - prev.astype(np.int16))
    return float((diff > pixel_delta).mean()) > threshold


class FrameDiff:
    """Captures frames in a background thread and validates motion via pixel diff.

    picamera2 is imported lazily in start() so the class is usable in unit tests
    on non-Pi machines without the library installed.
    """

    def __init__(
        self,
        threshold: float,
        resolution: tuple[int, int] = (640, 480),
        capture_fps: float = 2.0,
    ):
        self._threshold = threshold
        self._resolution = resolution
        self._capture_fps = capture_fps
        self._camera = None
        self._prev: np.ndarray | None = None
        self._curr: np.ndarray | None = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        from picamera2 import Picamera2

        self._camera = Picamera2()
        cfg = self._camera.create_preview_configuration(
            main={"size": self._resolution, "format": "RGB888"}
        )
        self._camera.configure(cfg)
        self._camera.start()
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.debug("FrameDiff started %s @ %.1f fps", self._resolution, self._capture_fps)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        if self._camera:
            self._camera.stop()
            self._camera.close()
            self._camera = None
        with self._lock:
            self._prev = None
            self._curr = None
        logger.debug("FrameDiff stopped")

    def check(self) -> bool:
        """Return True if the two most recent frames indicate motion."""
        with self._lock:
            prev, curr = self._prev, self._curr
        if prev is None or curr is None:
            return False
        return detect_motion(prev, curr, self._threshold)

    def _capture_loop(self) -> None:
        interval = 1.0 / self._capture_fps
        while self._running:
            try:
                frame = self._camera.capture_array()
                # Collapse RGB to grayscale luma for lightweight comparison.
                gray = frame.mean(axis=2).astype(np.uint8)
                with self._lock:
                    self._prev = self._curr
                    self._curr = gray
            except Exception:
                logger.exception("Frame capture error")
            time.sleep(interval)
