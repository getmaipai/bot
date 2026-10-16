from maipai_body.hal.seam import AntennaPositions
from maipai_body.presence.touch import AntennaTouchDetector


def _angles(left: float = 0.0, right: float = 0.0) -> AntennaPositions:
    return AntennaPositions(left=left, right=right)


def test_scripted_push_emits_once_and_rearms_only_at_small_deviation():
    detector = AntennaTouchDetector()
    assert detector.update(_angles(), _angles(left=0.5), now_s=0.00) is None
    assert detector.update(_angles(), _angles(left=0.5), now_s=0.02) is None
    event = detector.update(_angles(), _angles(left=0.5), now_s=0.04)
    assert event is not None and event.side == "left"
    assert detector.update(_angles(), _angles(left=0.5), now_s=0.30) is None
    detector.update(_angles(), _angles(left=0.05), now_s=0.31)
    assert detector.update(_angles(), _angles(left=0.5), now_s=0.32) is None
    assert detector.update(_angles(), _angles(left=0.5), now_s=0.34) is None
    assert detector.update(_angles(), _angles(left=0.5), now_s=0.36) is not None


def test_breathing_and_clip_motion_are_suppressed_during_and_after_drive():
    detector = AntennaTouchDetector()
    for index in range(21):
        now = index * 0.05
        assert detector.update(_angles(), _angles(left=0.55), now_s=now, driving=True) is None

    # A clip ends at 1.0 s; the full post-drive suppression is 260 ms.
    assert detector.update(_angles(), _angles(left=0.55), now_s=1.10) is None
    assert detector.update(_angles(), _angles(left=0.55), now_s=1.20) is None
    assert detector.update(_angles(), _angles(left=0.55), now_s=1.31) is None
    assert detector.update(_angles(), _angles(left=0.55), now_s=1.33) is None
    assert detector.update(_angles(), _angles(left=0.55), now_s=1.35) is not None


def test_double_crossing_merges_into_one_touch_event():
    detector = AntennaTouchDetector()
    first = [detector.update(_angles(), _angles(right=0.6), now_s=t) for t in (0.0, 0.02, 0.04)]
    assert sum(event is not None for event in first) == 1
    # The opposite antenna crosses while the same touch is still held.
    assert detector.update(_angles(), _angles(left=0.6, right=0.6), now_s=0.08) is None


def test_touch_during_offer_is_only_an_observation():
    detector = AntennaTouchDetector()
    events = [
        detector.update(_angles(), _angles(left=0.6), now_s=t, offer_active=True)
        for t in (0.0, 0.02, 0.04)
    ]
    event = next(event for event in events if event is not None)
    assert event.side == "left"
    assert not hasattr(event, "accepted")
