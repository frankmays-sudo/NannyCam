import logging
import subprocess
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class Recorder:
    """Manages a rpicam-vid subprocess that writes segmented H.264 footage.

    Call on_motion() on each confirmed motion event. Recording starts on the
    first call and continues until cooldown_seconds have elapsed with no new
    events, at which point the subprocess is terminated.

    on_motion() is safe to call from any thread (e.g. the GPIO interrupt thread).
    """

    def __init__(
        self,
        segment_dir: str | Path,
        segment_duration: int = 60,
        cooldown_seconds: float = 10.0,
        width: int = 1920,
        height: int = 1080,
        framerate: int = 30,
        on_start=None,
        on_stop=None,
    ):
        self._segment_dir = Path(segment_dir)
        self._segment_duration = segment_duration
        self._cooldown_seconds = cooldown_seconds
        self._width = width
        self._height = height
        self._framerate = framerate
        self._on_start = on_start  # called before rpicam-vid launches (e.g. framediff.stop)
        self._on_stop = on_stop    # called after rpicam-vid exits     (e.g. framediff.start)
        self._proc: subprocess.Popen | None = None
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def on_motion(self) -> None:
        """Notify the recorder that motion was confirmed."""
        with self._lock:
            if self._proc is None:
                self._start_locked()
            self._reschedule_cooldown_locked()

    def stop(self) -> None:
        """Immediately stop recording, cancelling any pending cooldown."""
        with self._lock:
            self._cancel_timer_locked()
            self._stop_locked()

    # ------------------------------------------------------------------
    # Internal helpers (all called with self._lock held)
    # ------------------------------------------------------------------

    def _start_locked(self) -> None:
        if self._on_start:
            self._on_start()
        self._segment_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = str(self._segment_dir / f"{ts}_%04d.h264")
        cmd = [
            "rpicam-vid",
            "--nopreview",
            "--codec", "h264",
            "--inline",          # embed SPS/PPS in each segment for independent playback
            "--segment", str(self._segment_duration * 1000),  # rpicam-vid uses ms
            "--output", output,
            "--timeout", "0",    # run until explicitly stopped
            "--width", str(self._width),
            "--height", str(self._height),
            "--framerate", str(self._framerate),
        ]
        try:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            logger.exception("Failed to launch rpicam-vid — restoring camera to framediff")
            if self._on_stop:
                self._on_stop()
            raise
        logger.info("Recording started (pid %d): %s", self._proc.pid, output)

    def _stop_locked(self) -> None:
        if self._proc is None:
            return
        pid = self._proc.pid
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        logger.info("Recording stopped (pid %d)", pid)
        self._proc = None
        if self._on_stop:
            self._on_stop()

    def _reschedule_cooldown_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self._cooldown_seconds, self._on_cooldown_expired)
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _on_cooldown_expired(self) -> None:
        with self._lock:
            self._timer = None
            self._stop_locked()
        logger.info("Cooldown expired — recording stopped")
