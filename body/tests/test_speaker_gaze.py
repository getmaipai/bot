"""Tests for the StackChan speaker-gaze controller (BOT-SC-GAZE-01)."""

from maipai_body.bodies.stackchan.speaker_gaze import GazeStep, SpeakerGaze


def _update(gaze, now, **overrides):
    kwargs = dict(speaking=True, face=None, bearing_rad=None, yaw=0.0, pitch=0.0)
    kwargs.update(overrides)
    return gaze.update(now, **kwargs)


def test_disabled_returns_none():
    gaze = SpeakerGaze(enabled=lambda: False)
    out = _update(gaze, 1.0, face=(0.5, 0.0))
    assert out is None


def test_not_speaking_returns_none():
    gaze = SpeakerGaze()
    out = _update(gaze, 1.0, speaking=False, face=(0.5, 0.0))
    assert out is None


def test_no_evidence_returns_none_and_never_scans():
    gaze = SpeakerGaze()
    assert _update(gaze, 1.0) is None
    assert _update(gaze, 10.0) is None
    assert _update(gaze, 100.0) is None


def test_centered_face_inside_deadband_returns_none():
    gaze = SpeakerGaze()
    assert _update(gaze, 1.0, face=(0.10, 0.10)) is None
    assert _update(gaze, 2.0, face=(-0.14, -0.14)) is None


def test_offset_face_steps_toward_it():
    gaze = SpeakerGaze()
    out = _update(gaze, 1.0, face=(0.3, 0.0))
    assert isinstance(out, GazeStep)
    assert out.yaw == 0.105  # 0.3 * 0.35 gain
    assert out.pitch == 0.0


def test_face_step_is_clamped_to_max_step():
    gaze = SpeakerGaze()
    out = _update(gaze, 1.0, face=(1.0, 1.0))
    assert out is not None
    assert out.yaw == 0.12
    assert out.pitch == 0.12


def test_rate_limit_is_one_step_per_second():
    gaze = SpeakerGaze()
    first = _update(gaze, 1.0, face=(0.5, 0.0))
    assert first is not None
    second = _update(gaze, 1.5, face=(0.5, 0.0), yaw=first.yaw, pitch=first.pitch)
    assert second is None
    third = _update(gaze, 2.0, face=(0.5, 0.0), yaw=first.yaw, pitch=first.pitch)
    assert third is not None


def test_absolute_yaw_and_pitch_limits_are_respected():
    gaze = SpeakerGaze()
    out = _update(gaze, 1.0, face=(1.0, 1.0), yaw=0.55, pitch=0.25)
    assert out is not None
    assert out.yaw == 0.6
    assert out.pitch == 0.3
    out_neg = _update(gaze, 3.0, face=(-1.0, -1.0), yaw=-0.55, pitch=-0.25)
    assert out_neg is not None
    assert out_neg.yaw == -0.6
    assert out_neg.pitch == -0.3


def test_bearing_without_face_turns_once_per_burst():
    gaze = SpeakerGaze()
    first = _update(gaze, 1.0, bearing_rad=0.5)
    assert isinstance(first, GazeStep)
    assert first.yaw == 0.12
    assert first.pitch == 0.0
    # No second step while the speaking burst continues.
    second = _update(gaze, 3.0, bearing_rad=0.5, yaw=first.yaw)
    assert second is None


def test_bearing_below_threshold_does_not_turn():
    gaze = SpeakerGaze()
    assert _update(gaze, 1.0, bearing_rad=0.2) is None


def test_negative_bearing_turns_negative():
    gaze = SpeakerGaze()
    out = _update(gaze, 1.0, bearing_rad=-0.5)
    assert out is not None
    assert out.yaw == -0.12


def test_burst_resets_only_after_two_seconds_of_silence():
    gaze = SpeakerGaze()
    first = _update(gaze, 1.0, bearing_rad=0.5)
    assert first is not None
    # A short pause does not reset the burst.
    _update(gaze, 1.5, speaking=False)
    second = _update(gaze, 2.0, bearing_rad=0.5, yaw=first.yaw)
    assert second is None
    # Two seconds of silence resets the burst.
    _update(gaze, 3.0, speaking=False)
    _update(gaze, 5.0, speaking=False)
    third = _update(gaze, 5.5, bearing_rad=0.5, yaw=first.yaw)
    assert third is not None
    assert third.yaw == first.yaw + 0.12


def test_sign_convention():
    gaze = SpeakerGaze()
    out = _update(gaze, 1.0, face=(0.3, 0.2))
    assert out is not None
    # Face right of center: yaw moves right (positive).
    assert out.yaw > 0.0
    # Face below center: pitch moves down (positive).
    assert out.pitch > 0.0
    out_left = _update(gaze, 3.0, face=(-0.3, -0.2))
    assert out_left is not None
    assert out_left.yaw < 0.0
    assert out_left.pitch < 0.0
