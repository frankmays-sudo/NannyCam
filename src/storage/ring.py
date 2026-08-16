import logging
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Segment:
    path: Path
    name: str
    size_bytes: int
    mtime: float


def list_segments(segment_dir: Path) -> list[Segment]:
    """Return all .h264 segments in segment_dir, oldest first.

    Skips files that vanish mid-stat (e.g. concurrently rotated by rpicam-vid).
    """
    if not segment_dir.is_dir():
        return []

    out: list[Segment] = []
    for p in segment_dir.glob("*.h264"):
        try:
            st = p.stat()
            out.append(Segment(path=p, name=p.name, size_bytes=st.st_size, mtime=st.st_mtime))
        except FileNotFoundError:
            pass

    out.sort(key=lambda s: s.mtime)  # oldest first
    return out


def enforce_quota(segment_dir: Path, quota_bytes: int) -> list[Path]:
    """Delete the oldest .h264 segments until total usage is within quota_bytes.

    The most-recently-modified file is always protected from deletion because
    libcamera-vid may still be writing to it.  Returns the list of deleted paths.
    """
    segments = list_segments(segment_dir)

    if len(segments) <= 1:
        return []  # never delete the only remaining file

    total = sum(s.size_bytes for s in segments)
    if total <= quota_bytes:
        return []

    deleted: list[Path] = []
    candidates = segments[:-1]  # exclude newest — may be actively written
    for seg in candidates:
        if total <= quota_bytes:
            break
        try:
            seg.path.unlink()
            deleted.append(seg.path)
            logger.info("Deleted segment %s (%d bytes)", seg.name, seg.size_bytes)
        except FileNotFoundError:
            pass
        total -= seg.size_bytes  # deduct regardless — file is gone either way

    return deleted


class StorageRing:
    """Periodically enforces the footage quota by removing the oldest segments.

    Uses a threading.Event so stop() wakes the sleeping thread immediately
    rather than waiting for the next poll tick.
    """

    def __init__(
        self,
        segment_dir: str | Path,
        quota_bytes: int,
        poll_interval: float = 30.0,
    ):
        self._segment_dir = Path(segment_dir)
        self._quota_bytes = quota_bytes
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        logger.info("StorageRing started (quota=%d bytes, poll=%.0fs)", self._quota_bytes, self._poll_interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("StorageRing stopped")

    def _watch_loop(self) -> None:
        while True:
            try:
                deleted = enforce_quota(self._segment_dir, self._quota_bytes)
                if deleted:
                    logger.debug("Quota sweep removed %d segment(s)", len(deleted))
            except Exception:
                logger.exception("Quota enforcement error")
            if self._stop_event.wait(timeout=self._poll_interval):
                break  # stop() was called
