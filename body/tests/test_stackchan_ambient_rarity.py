"""Ambient looking around stays rare (owner, 2026-11-13: "it looks around too much").

Replays of the live log's shapes on a fake clock: the owner at the desk seen most of the time
and briefly lost, movement only, a picture that only differs from the empty room, an empty room,
and a dark room. Live log 2026-11-13 09:00 to 09:50 had 16 looks in 50 minutes."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from maipai_body.app import StackChanBehavior
from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.bodies.stackchan.head_search import (
    AMBIENT_FACE_QUIET_S,
    AMBIENT_HOLD_S,
    AMBIENT_MOVE_QUIET_S,
    AMBIENT_PER_HOUR,
    DARK_COOLDOWN_S,
    HeadSearch,
)
from maipai_body.bodies.stackchan.presence_watch import PERSON_SHARE

ROOM = np.full((12, 16), 120.0, dtype=np.float32)
BODY = ROOM.copy()
BODY[:, :10] = 40.0


class _Vision:
    """A bridge with a face, movement and a luma that the test sets, one look per call."""

    def __init__(self, *, luma: float | None = 120.0, thumb=BODY):
        self.detected = False
        self.motion: float | None = None
        self.luma = luma
        self.thumb = thumb
        self.last_motion = 0.0

    def track_stream_frame(self, *, deadline_s=0.4, may_move=None):
        return SimpleNamespace(detected=self.detected, x=0.5, y=0.3)

    def motion_age(self):
        return self.motion

    def latest_look(self, *, max_age_s, take=False):
        return (b"\xff\xd8", 1 if self.detected else 0, self.luma, self.thumb)


def _behavior(vision):
    device = FakeStackChanDeviceClient()
    behavior = StackChanBehavior(StackChanRobotAdapter(device).robot, vision_bridge=vision)
    behavior.idle_level = "normal"
    behavior.idle_still = lambda: False
    behavior.watch_level = lambda: "presence"
    behavior.night_active = lambda: False
    return behavior


def _run(behavior, vision, start, seconds, *, face=lambda t: False, motion=lambda t: None):
    """Tick the presence loop every half second; return when each ambient look started."""
    starts = []
    t = start
    while t < start + seconds:
        vision.detected = face(t)
        vision.motion = motion(t)
        behavior.watch_for_faces(t)
        was = behavior._search.active
        behavior.search_tick(t)
        if behavior._search.active and not was:
            starts.append((t, behavior._search.reason))
        t += 0.5
    return starts


def test_the_owner_at_the_desk_seen_and_briefly_lost_starts_no_look_for_five_minutes():
    """09:03 to 09:50: a face in 69 of 88 looks a minute, movement all the time, the picture 60 to
    83 percent unlike the empty room. Seen every minute but a short gap: not one look."""
    vision = _Vision()
    behavior = _behavior(vision)
    try:
        behavior._baseline.learn(ROOM, 0.0)
        # A face most of every minute; lost for 40 seconds out of each minute, still moving.
        starts = _run(
            behavior,
            vision,
            1020.0,
            1800.0,
            face=lambda t: (t % 60) < 20,
            motion=lambda t: 0.5,
        )
        assert starts == []
        # Lost for good, still moving: the first look waits for the five quiet minutes and the
        # same trigger holding for AMBIENT_HOLD_S, never earlier.
        last_face = 2800.0 - 40.0  # the last face look of the minute ends at :20
        starts = _run(behavior, vision, 2800.0, 700.0, motion=lambda t: 0.5)
        assert starts, "someone moving with no face for ten minutes may get one look"
        assert starts[0][0] >= last_face + AMBIENT_FACE_QUIET_S
        assert starts[0][0] >= last_face + AMBIENT_FACE_QUIET_S + AMBIENT_HOLD_S - 1.0
    finally:
        behavior.close()


def test_movement_for_a_moment_is_not_enough_it_has_to_hold():
    vision = _Vision()
    behavior = _behavior(vision)
    try:
        # A hand passes the lens for five seconds, again and again with a gap: never one look.
        starts = _run(
            behavior,
            vision,
            1000.0,
            600.0,
            motion=lambda t: 0.5 if (t % 30) < 3 else 20.0,
        )
        assert starts == []
        # Movement that does not stop: one look after AMBIENT_HOLD_S.
        starts = _run(behavior, vision, 2000.0, 60.0, motion=lambda t: 0.5)
        assert [r for _, r in starts] == ["person"]
        assert starts[0][0] >= 2000.0 + AMBIENT_HOLD_S - 1.0
    finally:
        behavior.close()


def test_a_picture_unlike_the_empty_room_with_nothing_moving_starts_nothing_for_an_hour():
    vision = _Vision()
    behavior = _behavior(vision)
    try:
        behavior._baseline.learn(ROOM, 0.0)
        assert _run(behavior, vision, 1000.0, 60.0) == []
        assert behavior._person_share >= PERSON_SHARE  # the picture really is unlike the empty room
        assert _run(behavior, vision, 1060.0, 3540.0) == []
    finally:
        behavior.close()


def test_an_empty_lit_room_starts_nothing():
    vision = _Vision(thumb=ROOM)
    behavior = _behavior(vision)
    try:
        behavior._baseline.learn(ROOM, 0.0)
        assert _run(behavior, vision, 1000.0, 3600.0) == []
    finally:
        behavior.close()


def test_never_more_than_four_ambient_looks_an_hour_and_the_same_scene_only_once():
    """Movement that never stops and a picture that never changes (the 09:00 hour): one look, and
    no second one for the same scene; with a scene that keeps changing the hour cap holds."""
    vision = _Vision()
    behavior = _behavior(vision)
    try:
        starts = _run(behavior, vision, 1000.0, 3600.0, motion=lambda t: 0.5)
        assert len(starts) == 1
    finally:
        behavior.close()
    search = HeadSearch(clock=lambda: 0.0)
    began = []
    t = 0.0
    while t < 7200.0:
        if search.start("person", t):
            began.append(t)
            search.stop(t + 6.0, found=True)  # a face each time: no back-off, only the cap
        t += 10.0
    in_hour = [b for b in began if b < 3600.0]
    assert len(in_hour) == AMBIENT_PER_HOUR
    assert all(len([b for b in began if x <= b < x + 3600.0]) <= AMBIENT_PER_HOUR for x in began)
    # The spoken requests and the look after someone spoke are exempt from the cap.
    capped = HeadSearch(clock=lambda: 0.0)
    for i in range(AMBIENT_PER_HOUR):
        assert capped.start("person", i * 10.0)
        capped.stop(i * 10.0 + 6.0, found=True)
    assert not capped.may_start("person", 100.0)
    assert not capped.may_start("dark", 100.0)
    assert capped.may_start("ask", 100.0) and capped.may_start("ask_level", 100.0)
    assert capped.may_start("speaker", 100.0)


def test_no_ambient_look_within_two_minutes_after_the_head_last_moved():
    vision = _Vision()
    behavior = _behavior(vision)
    try:
        behavior._note_own_move()
        vision.motion = 20.0
        behavior.watch_for_faces(1000.0)  # stamps the move
        starts = _run(behavior, vision, 1000.5, 300.0, motion=lambda t: 0.5 if t > 1050 else None)
        assert starts and starts[0][0] >= 1000.0 + AMBIENT_MOVE_QUIET_S
    finally:
        behavior.close()


def test_the_dark_check_runs_at_most_once_in_thirty_minutes_and_never_with_someone_in_view():
    vision = _Vision(luma=None)
    behavior = _behavior(vision)
    behavior.lux = lambda: 1.8  # the sensor at its floor
    try:
        # A face was just seen: the dark check waits out the five minutes (the lens may be
        # covered by them, or they are sitting there).
        vision.detected = True
        behavior.watch_for_faces(1000.0)
        vision.detected = False
        starts = _run(behavior, vision, 1001.0, 280.0)
        assert starts == []
        # Movement counts as in view too: five quiet minutes after the last of it.
        moving = lambda t: 0.5 if t < 1290.0 else None  # noqa: E731
        assert _run(behavior, vision, 1281.0, 304.0, motion=moving) == []
        # Nobody for a long while and a dark sensor: one check, then not for 30 minutes.
        starts = _run(behavior, vision, 1585.0, 3 * 1800.0)
        assert [r for _, r in starts][0] == "dark" and starts[0][0] >= 1290.0 + 300.0
        dark = [t for t, r in starts if r == "dark"]
        assert all(b - a >= DARK_COOLDOWN_S for a, b in zip(dark, dark[1:], strict=False))
        assert len(dark) <= 3
    finally:
        behavior.close()


def test_the_spoken_find_me_sweep_is_exempt_from_every_rule():
    vision = _Vision()
    behavior = _behavior(vision)
    try:
        vision.detected = True
        behavior.watch_for_faces(1000.0)  # a face seconds ago
        vision.detected = False
        behavior._note_own_move()
        behavior.watch_for_faces(1000.5)  # and the head just moved
        for i in range(AMBIENT_PER_HOUR):
            behavior._search._ambient_starts.append(1000.0 - i)  # the hourly cap is used up
        behavior._find_request = ("ask", 1001.0)
        behavior.search_tick(1001.0)
        assert behavior._search.reason == "ask"
    finally:
        behavior.close()
