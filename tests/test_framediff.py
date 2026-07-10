import numpy as np
import pytest

from src.motion.framediff import FrameDiff, detect_motion


def frame(value: int, h: int = 480, w: int = 640) -> np.ndarray:
    return np.full((h, w), value, dtype=np.uint8)


# --- detect_motion (pure logic, no hardware) ---

def test_identical_frames_no_motion():
    f = frame(100)
    assert not detect_motion(f, f, threshold=0.02)

def test_fully_changed_frame_is_motion():
    assert detect_motion(frame(0), frame(100), threshold=0.02)

def test_below_threshold_no_motion():
    prev = frame(0)
    curr = prev.copy()
    # 5 rows × 640 cols = 3200 pixels = 1.04% of 307200 → below 2% threshold
    curr[:5, :] = 100
    assert not detect_motion(prev, curr, threshold=0.02)

def test_above_threshold_motion():
    prev = frame(0)
    curr = prev.copy()
    # 15 rows × 640 cols = 9600 pixels = 3.125% → above 2% threshold
    curr[:15, :] = 100
    assert detect_motion(prev, curr, threshold=0.02)

def test_pixel_delta_sensitivity():
    prev = frame(100)
    curr = frame(110)  # only 10-unit intensity change
    # delta=25 → change of 10 is sub-threshold → no motion
    assert not detect_motion(prev, curr, threshold=0.02, pixel_delta=25)
    # delta=5 → change of 10 exceeds it → motion
    assert detect_motion(prev, curr, threshold=0.02, pixel_delta=5)


# --- FrameDiff.check() (no camera — inject frames directly) ---

class TestFrameDiffCheck:
    def test_no_frames_returns_false(self):
        fd = FrameDiff(threshold=0.02)
        assert not fd.check()

    def test_only_one_frame_returns_false(self):
        fd = FrameDiff(threshold=0.02)
        fd._curr = frame(50)
        assert not fd.check()

    def test_motion_with_different_frames(self):
        fd = FrameDiff(threshold=0.02)
        fd._prev = frame(0)
        fd._curr = frame(100)
        assert fd.check()

    def test_no_motion_with_identical_frames(self):
        fd = FrameDiff(threshold=0.02)
        f = frame(50)
        fd._prev = f
        fd._curr = f.copy()
        assert not fd.check()
