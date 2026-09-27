"""Behavior the seam promises for the Reachy Mini profile.

Runs against the fake always, and against the live simulator only when
`MAIPAI_BODY_LIVE=1` and a daemon answers on localhost:8000 (`conftest.py`'s
`body` fixture); otherwise the live parametrization is skipped with a
reason, never failed.
"""

from __future__ import annotations

import math
import time

import pytest

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniBody, build_fake_body
from maipai_body.hal.errors import BodyLost, OutOfEnvelope
from maipai_body.hal.seam import HeadPose


def _is_fake(body) -> bool:
    return isinstance(body, FakeReachyMiniBody)


def _latest(frames_iter, count: int) -> object:
    """Drain `count` buffered frames and return the last one.

    The live feed's WebSocket connection buffers frames in the background
    while the caller is doing something else (blocking on a `goto`,
    sleeping); a single `next()` right after would hand back the oldest
    buffered frame, not the current state. Draining a batch sized for the
    time that just elapsed gets past the backlog.
    """
    frame = None
    for _ in range(count):
        frame = next(frames_iter)
    return frame


def test_goto_inside_envelope_is_accepted_and_reaches_the_daemon(body):
    pose = HeadPose(pitch=math.radians(10), yaw=math.radians(15))
    antennas = (0.05, -0.05)
    body_yaw = math.radians(5)

    if _is_fake(body):
        body.head.goto(pose, antennas, body_yaw, duration_s=0.3)
        assert body.state.last_goto is not None
        assert body.state.last_goto["pose"] == pose
        assert body.state.last_goto["antennas"] == antennas
        assert body.state.last_goto["duration_s"] == 0.3
    else:
        # Tests share one persistent daemon; start from a known neutral
        # pose so this test's own move is unambiguous no matter what an
        # earlier test left the head doing.
        body.head.goto(HeadPose(), (0.0, 0.0), 0.0, duration_s=0.3)
        frames = body.state_feed.frames()
        before = _latest(frames, 3)
        body.head.goto(pose, antennas, body_yaw, duration_s=0.5)
        # duration_s=0.5 at the feed's 20 Hz default buffers ~10 frames
        # while goto() blocks; drain past all of them.
        after = _latest(frames, 15)
        assert abs(after.head_pose.pitch - before.head_pose.pitch) > math.radians(1)
        assert abs(after.head_pose.yaw - before.head_pose.yaw) > math.radians(1)


def test_goto_outside_envelope_raises_and_the_daemon_receives_nothing(body):
    # +80 degrees of pitch is past the profile's +/-40 degree envelope.
    pose = HeadPose(pitch=math.radians(80))

    if _is_fake(body):
        with pytest.raises(OutOfEnvelope):
            body.head.goto(pose, None, None, duration_s=0.3)
        # check_envelope raises before FakeHeadActuator.goto ever touches
        # `body.state`, so nothing was recorded as sent.
        assert body.state.last_goto is None
    else:
        # check_envelope raises before the SDK's goto_target is ever
        # called, so the daemon never sees this command either.
        with pytest.raises(OutOfEnvelope):
            body.head.goto(pose, None, None, duration_s=0.3)


def test_body_yaw_only_command_still_checks_the_head_to_body_delta():
    # Fake-only: this checks `check_envelope`'s own bookkeeping of the last
    # commanded head yaw, shared code the live client uses too, so the
    # fake is a faithful proof without needing the live daemon to accept
    # a specific pose right at the delta boundary.
    body = build_fake_body()
    body.head.goto(HeadPose(yaw=math.radians(170)), None, math.radians(150), duration_s=0.2)

    # A body-yaw-only command with no pose: 170 - 90 = 80 degrees of
    # head-to-body delta, past the profile's +/-65 degree limit, must
    # still raise even though this command sets no pose of its own.
    with pytest.raises(OutOfEnvelope):
        body.head.goto(None, None, math.radians(90), duration_s=0.2)

    body.close()


def test_hold_after_goto_stops_motion(body):
    pose = HeadPose(pitch=math.radians(10))
    body.head.goto(pose, None, None, duration_s=0.3)
    frames = body.state_feed.frames()

    if _is_fake(body):
        for _ in range(3):
            next(frames)
        body.head.hold()
        first = next(frames)
        second = next(frames)
        assert first.head_pose == second.head_pose
        assert first.antennas == second.antennas
        assert first.body_yaw == second.body_yaw
    else:
        body.head.hold()
        # let the hold's own target settle in the physics sim before the
        # first "now it's stopped" sample.
        time.sleep(0.2)
        first = _latest(frames, 5)
        time.sleep(0.2)
        second = _latest(frames, 5)
        assert abs(second.head_pose.pitch - first.head_pose.pitch) < math.radians(1)
        assert abs(second.head_pose.yaw - first.head_pose.yaw) < math.radians(1)
        assert abs(second.body_yaw - first.body_yaw) < math.radians(1)


def test_state_frames_are_typed_ordered_and_stamped_monotonically(body):
    frames = body.state_feed.frames()
    samples = [next(frames) for _ in range(5)]

    stamps = [f.monotonic_ns for f in samples]
    assert all(isinstance(s, int) for s in stamps)
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == len(stamps)
    for f in samples:
        assert isinstance(f.head_pose, HeadPose)
        assert isinstance(f.antennas, tuple) and len(f.antennas) == 2


def test_losing_the_connection_raises_body_lost_and_refuses_further_commands():
    # Forcing a live daemon to drop its connection mid-suite would break
    # every test that runs after it against the shared simulator, so this
    # one is fake-only: `simulate_connection_loss` sets the same "lost"
    # flag a real ConnectionError/TimeoutError would set in `client.py`.
    body = build_fake_body()
    body.simulate_connection_loss()

    with pytest.raises(BodyLost):
        body.head.goto(HeadPose(), None, None, duration_s=0.2)
    with pytest.raises(BodyLost):
        body.head.enable()
    with pytest.raises(BodyLost):
        next(body.state_feed.frames())

    body.close()


def test_capability_list_matches_the_vocabulary_on_both_fake_and_live(body):
    assert set(body.profile.capabilities) == {
        "head_6dof",
        "roll",
        "antennas",
        "body_yaw",
        "camera",
        "mic",
        "speaker",
        "doa",
        "state_feed",
        "imu",
        "moves_recorded",
        "speech_pod",
    }
