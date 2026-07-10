import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


def enforce_quota(segment_dir: Path, quota_bytes: int) -> list[Path]:
    """Delete the oldest .h264 segments until total usage is within quota_bytes.

    The most-recently-modified file is always protected from deletion because
    libcamera-vid may still be writing to it.  Returns the list of deleted paths.
    """
    if not segment_dir.is_dir():
        return []

    entries: list[tuple[float, int, Path]] = []
    for p in segment_dir.glob("*.h264"):
        try:
            st = p.stat()
            entries.append((st.st_mtime, st.st_size, p))
        except FileNotFoundError:
            pass

    entries.sort()  # oldest mtime first

    if len(entries) <= 1:
        return []  # never delete the only remaining file

    total = sum(size for _, size, _ in entries)
    if total <= quota_bytes:
        return []

    deleted: list[Path] = []
    candidates = entries[:-1]  # exclude newest — may be actively written
    for _, size, path in candidates:
        if total <= quota_bytes:
            break
        try:
            path.unlink()
            deleted.append(path)
            logger.info("Deleted segment %s (%d bytes)", path.name, size)
        except FileNotFoundError:
            pass
        total -= size  # deduct regardless — file is gone either way

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
