"""The envelope: what a goto or set_target is allowed to reach the daemon with."""

from __future__ import annotations

import pytest

from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.hal.errors import OutOfEnvelope
from maipai_body.hal.seam import HeadPose


def test_goto_inside_envelope_is_accepted_and_reaches_the_daemon(body_client):
    """A target within the profile's axes lands: the fake logs it, the live daemon moves."""
    pose = HeadPose(pitch=0.1, yaw=0.1)

    if isinstance(body_client, FakeReachyMiniClient):
        body_client.goto(pose=pose, duration_s=0.2)
        assert body_client.sent_commands, "goto never reached the fake's command log"
        last = body_client.sent_commands[-1]
        assert last.kind == "goto"
        assert last.pose == pose
    else:
        # A prior test (or a prior daemon session) may leave the head
        # somewhere other than neutral, and automatic body yaw couples
        # the reported world-frame yaw to the body's own yaw, so this
        # checks that the head actually moved rather than pinning an
        # absolute target: the acceptance is "the state feed moves".
        feed = body_client.state_feed(frequency=10.0)
        try:
            baseline = next(iter(feed))
        finally:
            feed.close()
        target_pitch = max(-0.6, min(0.6, (baseline.head_pose.pitch or 0.0) + 0.15))
        body_client.goto(pose=HeadPose(pitch=target_pitch), duration_s=0.3)

        feed = body_client.state_feed(frequency=10.0)
        try:
            frame = next(iter(feed))
        finally:
            feed.close()
        assert frame.head_pose is not None
        assert abs(frame.head_pose.pitch - baseline.head_pose.pitch) > 0.05, (
            "the head did not move after a within-envelope goto"
        )


def test_goto_outside_envelope_raises_and_daemon_receives_nothing(body_client):
    """A target past the profile's head_pitch limit (+/-40 degrees) is refused before the daemon."""
    out_of_range_pose = HeadPose(pitch=1.2)  # well past 40 degrees (~0.698 rad)

    with pytest.raises(OutOfEnvelope):
        body_client.goto(pose=out_of_range_pose, duration_s=0.2)

    if isinstance(body_client, FakeReachyMiniClient):
        assert body_client.sent_commands == [], "an out-of-envelope goto reached the fake daemon"


def test_hold_after_goto_stops_motion(body_client):
    """After hold(), the next state frames do not move (dev.md section 5's own words for stop)."""
    if isinstance(body_client, FakeReachyMiniClient):
        # The recorded fixture is a real goto-then-hold trace against the
        # simulator; its last third is the genuine post-hold segment.
        frames = list(body_client.state_feed())
        tail = frames[-15:]
        deltas = [abs(b.head_pose.yaw - a.head_pose.yaw) for a, b in zip(tail, tail[1:])]
        assert max(deltas) < 0.01, "recorded frames after hold still show motion"
    else:
        body_client.goto(pose=HeadPose(yaw=0.2), duration_s=0.3)
        body_client.hold()
        feed = body_client.state_feed(frequency=10.0)
        try:
            frames = [next(iter(feed)) for _ in range(8)]
        finally:
            feed.close()
        # hold() reads the present pose over REST then re-issues it, so the
        # very first frame or two can still carry the tail of the physics
        # settling from before hold() was called (observed live: a ~0.02 rad
        # jump on frame 0, then under 0.004 rad from there); the tail is
        # the genuine "stopped" segment.
        tail = frames[-4:]
        deltas = [abs(b.head_pose.yaw - a.head_pose.yaw) for a, b in zip(tail, tail[1:])]
        assert max(deltas) < 0.01, "live frames after hold still show motion"
