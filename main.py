#!/usr/bin/env python3
"""NannyCam entry point.

Reads config/settings.yaml, wires up all components, and blocks until
SIGINT or SIGTERM.

Camera handoff:
  FrameDiff holds the camera (via picamera2) while idle.  Because libcamera-vid
  takes exclusive camera access, the on_start hook stops FrameDiff before
  recording begins, and the on_stop hook restarts it after libcamera-vid exits.

Shutdown order:
  recorder.stop() first — triggers the on_stop hook so framediff is restarted
  and can be cleanly stopped by detector.stop() immediately after.
"""

import logging
import signal
import sys
from pathlib import Path

import yaml

from src.motion.detector import MotionDetector
from src.motion.framediff import FrameDiff
from src.motion.pir import PIRSensor
from src.recording.recorder import Recorder
from src.storage.ring import StorageRing


def _load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    cfg = _load_config(Path(__file__).parent / "config" / "settings.yaml")
    m = cfg["motion"]
    r = cfg["recording"]
    s = cfg["storage"]

    framediff = FrameDiff(
        threshold=m["framediff_threshold"],
        resolution=tuple(m["framediff_resolution"]),
        capture_fps=m["framediff_fps"],
    )

    recorder = Recorder(
        segment_dir=r["segment_dir"],
        segment_duration=r["segment_duration"],
        cooldown_seconds=m["cooldown_seconds"],
        width=r["width"],
        height=r["height"],
        framerate=r["framerate"],
        on_start=framediff.stop,   # release camera before libcamera-vid claims it
        on_stop=framediff.start,   # reclaim camera after libcamera-vid exits
    )

    detector = MotionDetector(
        pir=PIRSensor(pin=m["pir_pin"]),
        framediff=framediff,
        on_motion=recorder.on_motion,
    )

    ring = StorageRing(
        segment_dir=r["segment_dir"],
        quota_bytes=s["quota_bytes"],
        poll_interval=s["poll_interval_seconds"],
    )

    def shutdown(sig, _frame) -> None:
        logger.info("Shutting down (signal %d)", sig)
        recorder.stop()   # terminates libcamera-vid; on_stop restarts framediff
        detector.stop()   # removes PIR interrupt; stops framediff
        ring.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("NannyCam starting")
    ring.start()
    detector.start()   # starts framediff then arms the PIR interrupt
    logger.info("NannyCam running — waiting for motion")

    signal.pause()     # block main thread; all work happens in daemon threads


if __name__ == "__main__":
    main()
