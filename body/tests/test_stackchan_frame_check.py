import numpy as np

from maipai_body.bodies.stackchan.frame_check import EVERY_S, REPORT_S, FrameCheck


class FakeDetector:
    """Finds a 'face' only when the frame's first pixel row is bright, and says how close."""

    def __init__(self):
        self.best_score = 0.0
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        self.best_score = 0.9 if frame[0, 0, 0] == 200 else 0.1
        return []


def test_it_tries_other_forms_and_reports_only_scores():
    clock = [0.0]
    check = FrameCheck(clock=lambda: clock[0])
    detector = FakeDetector()
    frame = np.zeros((6, 8, 3), dtype=np.uint8)
    frame[-1, -1, :] = 200  # bright pixel in the corner: the rotated-180 form puts it first
    detector.best_score = 0.1
    check.note(detector, frame, 3000)
    assert detector.calls == 6
    assert check.report(0.0) is None
    clock[0] = REPORT_S + 1
    line = check.report(clock[0])
    assert "8x6" in line and "rot180 0.90" in line and "as-is 0.10" in line
    assert "StackChan frame check" in line


def test_the_extra_forms_are_tried_at_most_every_ten_seconds():
    clock = [0.0]
    check = FrameCheck(clock=lambda: clock[0])
    detector = FakeDetector()
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    check.note(detector, frame, 100)
    check.note(detector, frame, 100)
    assert detector.calls == 6
    clock[0] = EVERY_S + 0.1
    check.note(detector, frame, 100)
    assert detector.calls == 12


def test_a_detector_without_a_score_is_left_alone():
    check = FrameCheck()
    check.note(object(), np.zeros((4, 4, 3), dtype=np.uint8), 100)
    assert check.report(0.0) is None
