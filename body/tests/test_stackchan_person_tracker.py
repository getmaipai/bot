"""Find the person, then the face, then follow: stages, aiming math, following, caps, back-offs."""

from __future__ import annotations

import pytest

from maipai_body.bodies.stackchan.person_tracker import (
    AIM_DEAD_ZONE,
    AIM_GAIN,
    AIM_MAX_MOVES,
    AIM_MAX_STEP_DEG,
    AIM_SETTLE_S,
    AIM_SPEED,
    AIM_TILT_STEP_DEG,
    ATTEMPT_CAP_S,
    BACKOFF_S,
    FACE_GONE_S,
    FOLLOW_LOST_S,
    FOLLOW_MAX_STEP_DEG,
    FOLLOW_SPEED,
    GIVE_UP_S,
    MAX_ATTEMPTS,
    PERSON_SCORE,
    RELAX_AFTER_S,
    RETRY_MOVE,
    SEARCH_MAX_POSES,
    SEARCH_PAN_DEG,
    STILL_FOR_SEARCH_S,
    TILT_MAX_DEG,
    TILT_STEP_DEG,
    WAIT_HINT_MAX_S,
    PersonBox,
    PersonTracker,
    choose_person,
    yaw_error_deg,
)
from maipai_body.bodies.stackchan.profile import FOLLOW_YAW_SIGN, FOLLOW_YAW_SPAN_DEG

HALF = FOLLOW_YAW_SPAN_DEG / 2 * FOLLOW_YAW_SIGN  # the yaw of a person at the picture's right edge


def box(
    cx: float, top: float = 0.3, w: float = 0.3, h: float = 0.6, score: float = 0.8
) -> PersonBox:
    return PersonBox(cx - w / 2, top, w, h, score)


def observe(tracker, now, boxes, *, face_age=None, look_at=None, face_xy=None):
    return tracker.observe(
        now, boxes, face_age=face_age, look_at=now if look_at is None else look_at, face_xy=face_xy
    )


def start(tracker, now=10.0, cx=0.2, top=0.3):
    """Two looks with a box and no face start an attempt; returns the second action."""
    observe(tracker, now - 0.5, [box(cx, top)])
    return observe(tracker, now, [box(cx, top)])


def settle(tracker, now, action):
    """When the next look may be judged after this move."""
    return now + action.move.duration_s + AIM_SETTLE_S + 0.1


# -- box to head -----------------------------------------------------------------------------


def test_the_box_centre_maps_to_yaw_like_face_following_with_the_units_sign():
    assert yaw_error_deg(box(0.5)) == 0.0
    assert yaw_error_deg(box(0.0)) == pytest.approx(-HALF)
    assert yaw_error_deg(box(0.75)) == pytest.approx(HALF / 2)
    assert abs(yaw_error_deg(box(1.0))) == FOLLOW_YAW_SPAN_DEG / 2


def test_the_largest_box_wins_and_near_ties_pick_the_middle():
    left, right = box(0.2, w=0.3, h=0.6), box(0.8, w=0.1, h=0.2)
    assert choose_person([left, right]) == left
    tie_left, tie_middle = box(0.1, w=0.3, h=0.6), box(0.5, w=0.3, h=0.58)
    assert choose_person([tie_left, tie_middle]) == tie_middle
    assert choose_person([box(0.5, score=PERSON_SCORE - 0.01)]) is None
    # While an attempt runs, the earlier choice is kept when a box still overlaps where it was.
    assert choose_person([tie_left, tie_middle], last=box(0.12)) == tie_left


# -- aiming ------------------------------------------------------------------------------------


def test_an_attempt_needs_two_looks_with_a_box_and_no_face():
    tracker = PersonTracker()
    assert observe(tracker, 1.0, [box(0.2)]).kind == "none"  # one look is not enough
    assert tracker.stage == "idle"
    assert observe(tracker, 1.5, [box(0.2)], face_age=2.0).kind == "none"  # a face 2 s ago: not yet
    action = observe(tracker, 2.0, [box(0.2)], face_age=FACE_GONE_S + 1)
    assert action.kind == "move" and tracker.stage == "aiming"
    assert tracker.drain_events()[0].startswith("person seen at x 0.20")


def test_aiming_turns_toward_the_box_with_gain_and_cap_and_tilts_when_the_top_is_cut():
    tracker = PersonTracker()
    move = start(tracker, cx=0.2, top=0.3).move
    wanted = max(-AIM_MAX_STEP_DEG, min(AIM_MAX_STEP_DEG, yaw_error_deg(box(0.2)) * AIM_GAIN))
    assert move.yaw_deg == pytest.approx(wanted)
    assert move.pitch_deg == 0.0 and move.speed == AIM_SPEED and move.duration_s > 0
    assert tracker.pose == (move.yaw_deg, 0.0)
    far = PersonTracker()
    move = start(far, cx=1.0, top=0.0).move  # at the right edge, cut off at the top
    assert abs(move.yaw_deg) == pytest.approx(
        min(AIM_MAX_STEP_DEG, FOLLOW_YAW_SPAN_DEG / 2 * AIM_GAIN)
    )
    assert move.yaw_deg * HALF > 0  # toward the right edge, in the unit's own sign (profile.py)
    assert move.pitch_deg == AIM_TILT_STEP_DEG


def test_a_look_taken_before_the_head_settled_is_not_evidence():
    tracker = PersonTracker()
    action = start(tracker, now=10.0, cx=0.2)
    settled = 10.0 + action.move.duration_s + AIM_SETTLE_S
    # The same stale picture arrives twice: nothing moves.
    assert observe(tracker, 10.4, [box(0.2)], look_at=10.3).kind == "none"
    assert observe(tracker, settled + 0.1, [box(0.2)], look_at=settled - 0.05).kind == "none"
    # A frame after the settle counts: the person is still left of centre, so one more step.
    action = observe(tracker, settled + 0.6, [box(0.3)], look_at=settled + 0.5)
    assert action.kind == "move" and action.move.yaw_deg * HALF < 0  # still toward the left


def test_aiming_gives_up_on_centring_after_four_moves_and_follows_anyway():
    tracker = PersonTracker()
    action = start(tracker, now=10.0, cx=0.0)
    now, moves = 10.0, 1
    while tracker.stage == "aiming":
        now = settle(tracker, now, action)
        action = observe(tracker, now, [box(0.0)])  # never gets any closer
        if tracker.stage == "aiming":
            moves += 1
    assert moves == AIM_MAX_MOVES and tracker.stage == "follow"
    assert any("roughly on the person" in e for e in tracker.drain_events())


def test_someone_else_moving_the_head_is_remembered_so_the_next_aim_is_relative():
    tracker = PersonTracker()
    tracker.note_pose(-12.0, 15.0)
    move = start(tracker, now=10.0, cx=0.6).move
    assert move.yaw_deg == pytest.approx(-12.0 + yaw_error_deg(box(0.6)) * AIM_GAIN)
    assert move.pitch_deg == 15.0
    assert abs(0.6 - 0.5) > AIM_DEAD_ZONE


# -- the face search from a still body -----------------------------------------------------


def _centre_then_still(tracker):
    """Aim at a person who ends up centred and stands still: the face search begins."""
    start(tracker, now=10.0, cx=0.2)
    assert observe(tracker, 20.0, [box(0.5)]).kind == "none"  # centred once
    assert observe(tracker, 21.0, [box(0.5)]).kind == "none"  # twice: following the body
    assert tracker.stage == "follow"
    now = 21.0 + STILL_FOR_SEARCH_S + 0.1
    action = observe(tracker, now, [box(0.5)])
    assert tracker.stage == "face-search" and action.kind == "move"
    return now, action


def test_centred_and_still_starts_the_face_search_which_tilts_up_then_pans():
    tracker = PersonTracker()
    now, action = _centre_then_still(tracker)
    assert action.move.pitch_deg == TILT_STEP_DEG and action.move.yaw_deg == tracker.pose[0]
    yaw = action.move.yaw_deg
    poses = [action.move]
    while tracker.stage == "face-search":
        now = settle(tracker, now, action)
        action = observe(tracker, now, [box(0.5)])
        if tracker.stage == "face-search":
            poses.append(action.move)
    assert len(poses) == SEARCH_MAX_POSES
    pitches = [m.pitch_deg for m in poses]
    tilts = pitches[: SEARCH_MAX_POSES - 2]
    assert tilts == sorted(tilts) and tilts[-1] == TILT_MAX_DEG and max(pitches) <= TILT_MAX_DEG
    assert {round(m.yaw_deg - yaw) for m in poses[-2:]} == {-SEARCH_PAN_DEG, SEARCH_PAN_DEG}
    # A miss: back to following the body (the head comes down to it), no face search for a minute.
    assert (
        tracker.stage == "follow"
        and action.kind == "move"
        and "back to the body" in action.move.why
    )
    events = tracker.drain_events()
    assert any("aiming -> follow: centred" in e for e in events)
    assert any("follow -> face-search: standing still" in e for e in events)
    assert any(
        "face-search -> follow: no face in any pose" in e and "waits 60 s" in e for e in events
    )
    now = settle(tracker, now, action)
    for _ in range(5):
        now += 1.0
        assert observe(tracker, now, [box(0.5)]).kind == "none"  # still, in the dead zone: hold
    assert tracker.stage == "follow"


def test_a_face_during_the_search_or_the_aim_means_found_and_follow():
    tracker = PersonTracker()
    start(tracker, now=10.0, cx=0.2)
    action = observe(tracker, 13.4, [box(0.5)], face_age=0.2, face_xy=(0.5, 0.45))
    assert tracker.stage == "follow" and action.kind == "none"  # the face is centred: hold
    assert any(
        "aiming -> follow: face found after 3.4 s, 1 aim move(s)" in e
        for e in tracker.drain_events()
    )


# -- following -------------------------------------------------------------------------------


def test_following_turns_toward_a_walking_person_in_capped_natural_steps_and_holds_when_centred():
    tracker = PersonTracker()
    start(tracker, now=10.0, cx=0.5)
    observe(tracker, 11.0, [box(0.5)])
    assert tracker.stage == "follow"
    # They walk right: two fresh looks well outside the dead zone (one may be jitter) turn the
    # head a capped step.
    now = 12.0
    assert observe(tracker, now, [box(0.9)]).kind == "none"
    now += 0.5
    action = observe(tracker, now, [box(0.9)])
    assert action.kind == "move" and 0 < action.move.yaw_deg * HALF
    assert abs(action.move.yaw_deg) <= FOLLOW_MAX_STEP_DEG
    assert action.move.speed == FOLLOW_SPEED and "follow the body" in action.move.why
    first = action.move.yaw_deg
    now = settle(tracker, now, action)
    observe(tracker, now, [box(0.8)])  # the head turned, they kept walking
    now += 0.5
    action = observe(tracker, now, [box(0.8)])
    assert action.kind == "move" and abs(action.move.yaw_deg) > abs(
        first
    )  # relative to where it points
    assert "follow the body" in action.move.why
    now = settle(tracker, now, action)
    assert observe(tracker, now, [box(0.52)]).kind == "none"  # centred: hold
    assert tracker.stage == "follow"


def test_following_prefers_the_face_and_tilts_toward_it():
    tracker = PersonTracker()
    action = observe(tracker, 1.0, [], face_age=0.1, face_xy=(0.5, 0.1))  # a face high up
    assert tracker.stage == "follow"
    assert any("face seen at x 0.50, y 0.10 -> follow" in e for e in tracker.drain_events())
    # The first move after a find is immediate: up toward the face, no turn (it is centred).
    assert action.kind == "move" and action.move.pitch_deg > 0 and abs(action.move.yaw_deg) < 1e-6
    assert "follow the face" in action.move.why
    now = settle(tracker, 1.0, action)
    # A body box off to the side never pulls the head while the face is in view.
    assert observe(tracker, now, [box(0.1)], face_age=0.1, face_xy=(0.5, 0.5)).kind == "none"


def test_losing_sight_goes_back_to_aiming_after_two_seconds_and_rests_after_ten():
    tracker = PersonTracker()
    start(tracker, now=10.0, cx=0.5)
    observe(tracker, 11.0, [box(0.5)])
    assert tracker.stage == "follow"
    assert observe(tracker, 12.0, []).kind == "none"
    assert observe(tracker, 11.0 + FOLLOW_LOST_S + 0.1, []).kind == "none"
    assert tracker.stage == "aiming"
    assert any("follow -> aiming: lost sight" in e for e in tracker.drain_events())
    # They come back on the left: aiming turns there at once.
    action = observe(tracker, 14.0, [box(0.2)])
    assert action.kind == "move" and (action.move.yaw_deg - 0.0) * HALF < 0  # toward the left
    gone = PersonTracker()
    start(gone, now=10.0, cx=0.5)
    observe(gone, 11.0, [box(0.5)])
    observe(gone, 11.0 + FOLLOW_LOST_S + 0.1, [])
    action = observe(gone, 11.0 + GIVE_UP_S + 0.1, [])
    assert action.kind == "return" and gone.stage == "idle"
    assert any("nobody came back" in e for e in gone.drain_events())


def test_sitting_still_for_a_long_while_relaxes_and_a_move_wakes_it():
    tracker = PersonTracker()
    observe(tracker, 1.0, [], face_age=0.1, face_xy=(0.5, 0.5))
    now = 1.0
    action = None
    while tracker.stage == "follow":
        now += 2.0
        action = observe(tracker, now, [box(0.5)], face_age=0.1, face_xy=(0.5, 0.5))
    assert action.kind == "return" and now >= 1.0 + RELAX_AFTER_S
    assert any("relaxing until they move" in e for e in tracker.drain_events())
    # Still sitting there: nothing starts. A step across the room: it follows again.
    assert observe(tracker, now + 5, [box(0.5)], face_age=0.1, face_xy=(0.5, 0.5)).kind == "none"
    assert tracker.stage == "idle"
    observe(tracker, now + 6, [box(0.8)], face_age=0.1, face_xy=(0.8, 0.5))
    assert tracker.stage == "follow"


def test_the_follow_report_measures_how_far_off_centre_the_person_sat():
    tracker = PersonTracker()
    assert tracker.follow_report() is None
    start(tracker, now=10.0, cx=0.5)
    observe(tracker, 11.0, [box(0.5)])
    observe(tracker, 12.0, [box(0.7)])
    report = tracker.follow_report()
    assert report is not None and "follow move(s)" in report and "off centre" in report


# -- caps and back-offs ----------------------------------------------------------------------


def test_the_body_dropping_out_below_after_a_tilt_means_look_for_the_face_above():
    """Unit 2026-11-12 21:50: a person box cut off at the top, one aim move tilted up 15 degrees,
    the torso left the picture below and the attempt was wrongly called lost."""
    tracker = PersonTracker()
    tracker.note_pose(0.0, 22.0)
    action = start(tracker, now=10.0, cx=0.32, top=0.0)
    assert action.move.pitch_deg == 22.0 + AIM_TILT_STEP_DEG
    gone_at = settle(tracker, 10.0, action) + 2.0 + 0.5
    action = observe(tracker, gone_at, [])
    assert tracker.stage == "face-search" and action.kind == "move"
    assert action.move.pitch_deg > 22.0 + AIM_TILT_STEP_DEG
    assert any("dropped below the picture after the tilt" in e for e in tracker.drain_events())
    assert tracker._pitch_before_search == 22.0  # the head comes back to the body's height


def test_the_person_leaving_while_aiming_ends_the_attempt_and_the_head_returns():
    tracker = PersonTracker()
    action = start(tracker, now=10.0, cx=0.2)
    gone_at = settle(tracker, 10.0, action) + 2.0 + 0.5
    action = observe(tracker, gone_at, [])
    assert action.kind == "return" and tracker.stage == "idle"
    assert any("-> lost: the person left the picture" in e for e in tracker.drain_events())


def test_a_miss_backs_off_one_three_ten_minutes_unless_the_person_moves():
    tracker = PersonTracker()
    tracker._miss(100.0, "no face")
    assert not tracker.may_start(100.0 + BACKOFF_S[0] - 1)
    assert tracker.may_start(100.0 + BACKOFF_S[0])
    tracker._miss(200.0, "no face")
    assert tracker.may_start(200.0 + BACKOFF_S[1]) and not tracker.may_start(
        200.0 + BACKOFF_S[1] - 1
    )
    tracker._miss(300.0, "no face")
    assert not tracker.may_start(300.0 + BACKOFF_S[1])
    assert tracker.may_start(300.0 + BACKOFF_S[2])
    # They moved across the picture: the back-off no longer holds.
    moved = PersonTracker()
    start(moved, now=10.0, cx=0.2)
    moved._miss(20.0, "no face")
    start(moved, now=25.0, cx=0.2)
    assert moved.stage == "idle"  # same place: still waiting
    start(moved, now=30.0, cx=0.2 + RETRY_MOVE + 0.05)
    assert moved.stage == "aiming"


def test_at_most_three_attempts_in_ten_minutes_and_the_aim_is_capped():
    tracker = PersonTracker()
    for i in range(MAX_ATTEMPTS):
        assert tracker.start(float(i), box(0.5), "test").kind in ("none", "move")
        tracker.cancel(float(i) + 0.5, "test")
    assert not tracker.may_start(10.0)
    assert tracker.may_start(10.0 + 600.0)
    capped = PersonTracker()
    start(capped, now=10.0, cx=0.0)
    now = 10.0 + ATTEMPT_CAP_S + 0.1
    action = observe(capped, now, [box(0.0)])
    assert action.kind == "return" and any("ran out of time" in e for e in capped.drain_events())


def test_a_rest_cancels_without_counting_a_miss():
    tracker = PersonTracker()
    start(tracker, now=10.0, cx=0.2)
    tracker.cancel(11.0, "a rest started")
    assert tracker.stage == "idle" and tracker.may_start(11.0)
    assert any("aiming -> idle: a rest started" in e for e in tracker.drain_events())


def test_the_first_move_after_a_face_is_found_is_immediate_and_a_hint_keeps_the_head_there():
    """Unit 2026-11-12 22:18: the face was seen once at y 0.22 (well above the middle), the
    detector then flickered, and the head gave up and returned to rest after 8 s."""
    tracker = PersonTracker()
    action = observe(tracker, 1.0, [], face_age=0.1, face_xy=(0.48, 0.22))
    assert tracker.stage == "follow" and action.kind == "move" and action.move.pitch_deg > 0
    # The face flickers off, no box, but movement or a weak hint says they are still there:
    # the head comes back to level (a body is at the camera's height) and waits there.
    now = settle(tracker, 1.0, action)
    now += 3.0
    action = tracker.observe(now, [], face_age=now - 1.0, look_at=now, presence_hint=True)
    assert tracker.stage == "aiming" and action.kind == "move" and action.move.pitch_deg == 0.0
    now = settle(tracker, now, action)
    for i in range(12):
        now += 1.0
        action = tracker.observe(now, [], face_age=now - 1.0, look_at=now, presence_hint=True)
        assert action.kind == "none", i
    assert tracker.stage == "aiming"  # waiting
    # Nothing at all for ten seconds: back to rest.
    for _ in range(11):
        now += 1.0
        action = tracker.observe(now, [], face_age=now - 1.0, look_at=now, presence_hint=False)
    assert action.kind == "return" and tracker.stage == "idle"


def test_a_face_in_the_middle_band_never_tilts_the_head():
    """Unit 2026-11-12 22:24: a still face made ten small tilts in 30 s with the narrow band."""
    tracker = PersonTracker()
    observe(tracker, 1.0, [], face_age=0.1, face_xy=(0.5, 0.5))
    assert tracker.stage == "follow"
    now = 1.0
    for y in (0.35, 0.62, 0.4, 0.68, 0.33):  # the face box jitters inside the middle band
        now += 1.0
        assert observe(tracker, now, [], face_age=0.1, face_xy=(0.5, y)).kind == "none"
    now += 1.0
    observe(tracker, now, [], face_age=0.1, face_xy=(0.5, 0.15))  # high: one look
    now += 1.0
    action = observe(tracker, now, [], face_age=0.1, face_xy=(0.5, 0.15))  # two: tilt up
    assert action.kind == "move" and action.move.pitch_deg > 0


def test_a_walking_person_is_followed_on_the_first_look_with_a_small_lead():
    """Pacing test 2026-11-12: a target that moved more than the dead zone since the look before
    is acted on at once, aiming a little ahead of it."""
    tracker = PersonTracker()
    start(tracker, now=10.0, cx=0.5)
    observe(tracker, 11.0, [box(0.5)])
    assert tracker.stage == "follow"
    observe(tracker, 12.0, [box(0.5)])  # the look before
    action = observe(tracker, 12.5, [box(0.62)])  # walked 0.12 of the frame in half a second
    assert action.kind == "move" and action.move.speed == FOLLOW_SPEED
    plain = yaw_error_deg(box(0.62)) * 0.8
    assert abs(action.move.yaw_deg) > abs(plain)  # a lead ahead of them, in the same direction
    assert action.move.yaw_deg * plain > 0


def test_losing_a_follow_brings_the_head_back_to_level_and_the_hint_wait_is_capped():
    tracker = PersonTracker()
    observe(tracker, 1.0, [], face_age=0.1, face_xy=(0.5, 0.1))  # a high face: tilt up
    assert tracker.pose[1] > 0
    now = 10.0
    action = observe(tracker, now, [], face_age=5.0)
    assert tracker.stage == "aiming" and action.kind == "move" and action.move.pitch_deg == 0.0
    assert "back to level" in action.move.why
    now = settle(tracker, now, action)
    for _ in range(40):
        now += 1.0
        action = tracker.observe(now, [], face_age=now, look_at=now, presence_hint=True)
        if action.kind == "return":
            break
    assert action.kind == "return" and now - 10.0 <= WAIT_HINT_MAX_S + GIVE_UP_S + 2
