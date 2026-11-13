"""Find the person, then the face, then follow (owner design, approved 2026-11-12).

`docs/dev/stackchan-person-then-face-2026-11-12.md` is the design. The fast Look pass
(`vision/look_fast.py`) gives a person box even when only an arm or a torso is in view; this
tracker turns that box into a few head moves: aim the head at the person (yaw from the box
centre, a tilt up when the box is cut off at the top), then look for the face above the box in
small tilt steps and one small pan, and once the person is found, follow them: the face when one
is in view, the body when not, with smoothing, a dead zone and a speed that looks natural. It
knows nothing about servos or the camera: the behavior in app.py feeds it one look at a time (the
person boxes, the face, when the frame arrived) and performs the `Move` it returns, through the
head gate, never in a turn, asleep or at night. Every number that shapes the motion is at the top
of this file.

Frame budget (owner's live trial of 0.2.63, about 1.8 frames a second): a pose is judged only by a
look whose frame arrived after the move settled, never by wall time, so at that rate a move costs
about a second and the head never chases a stale picture. A head that follows is moved relative to
where it points (the pose it last commanded), so a person in the middle of the picture means
"stay", wherever the head is.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from maipai_body.bodies.stackchan.profile import (
    FOLLOW_PITCH_SPAN_DEG,
    FOLLOW_YAW_SIGN,
    FOLLOW_YAW_SPAN_DEG,
)

# A box below this score never moves the head: the Stack's own naming threshold. Measured on the
# unit 2026-11-12 (dim evening room, dark hoodie, backlit): the owner sitting back scored 0.41 to
# 0.55 as a person; an empty or black picture 0.00 to 0.03, so there is room below.
PERSON_SCORE = 0.35
# Measured on the unit 2026-11-12: the owner's dark hoodie filling the frame at desk distance
# scored 0.05 to 0.17 as a person, an empty or black picture 0.00 to 0.03. Above this the picture
# "may hold a person": the faint pink, and the glance-up look (head_search.py) for the face.
PERSON_HINT_SCORE = 0.1
PERSON_LOOKS = 2  # looks with a box, out of the last PERSON_WINDOW, before an attempt starts
PERSON_WINDOW = 3
FACE_GONE_S = 5.0  # no face this long before a body is acted on (as SEARCH_FACE_GONE_S)
FACE_FRESH_S = 1.0  # a face seen this recently is the target

AIM_DEAD_ZONE = 0.08  # of the frame width around the middle: centred, do not hunt
AIM_GAIN = 0.7  # share of the yaw error moved in one step
AIM_MAX_STEP_DEG = 30.0  # and the cap on one step
AIM_SPEED = 300  # servo speed: the spring is stiff enough to settle in about a second
AIM_SETTLE_S = 0.6  # after a move ends, before a look counts (a frame is up to 0.5 s old)
AIM_MAX_MOVES = 4
AIM_TIMEOUT_S = 6.0
CENTRED_LOOKS = 2  # looks in the dead zone before the face search starts
BOX_TOP_CUT = 0.05  # the box starts this close to the top edge: the person is cut off, tilt up
AIM_TILT_STEP_DEG = 25.0  # that tilt, with the yaw move (a seated person's face sits well above)
FOLLOW_CONFIRM_LOOKS = 2  # a follow move needs the error over the dead zone this many looks running

# Measured 2026-11-12: a person sitting at the desk fills the low camera's picture with their
# torso, and the face sits well above 30 degrees up; the search climbs to 60.
TILT_STEP_DEG = 15.0  # face search: tilt up this much per pose
TILT_MAX_DEG = 60.0  # never above this over level (the Robot clamps to the profile again)
SEARCH_HOLD_S = 0.8  # a face-search pose lasts about this long (then the frame budget decides)
SEARCH_PAN_DEG = 8.0  # the small pan each way at the top
SEARCH_MAX_POSES = 6  # four tilts and the two pans
SEARCH_TIMEOUT_S = 10.0  # six poses at about a second and a half each under the frame budget

# Following (owner, 2026-11-12: "follow me as I pace in the room").
FOLLOW_GAIN = 0.8  # share of the (predicted) error moved per step
FOLLOW_MAX_STEP_DEG = 25.0  # one step is never bigger: natural, not twitchy
FOLLOW_SPEED = 300  # servo speed while following: quick, the spring still eases it
FOLLOW_PITCH_GAIN = 0.5  # the head tilts toward the face more gently than it turns
# Measured 2026-11-12 22:24: with the sideways dead zone used for the tilt too, a still face made
# ten small tilts in 30 s (the face box jitters up and down). The face may sit anywhere in the
# middle 40 percent of the height; the head only tilts when it drifts out of that band.
FOLLOW_PITCH_DEAD_ZONE = 0.2
FOLLOW_SMOOTH = 0.6  # weight of the newest measurement in the smoothed target (1 = none)
# A walking person (owner's pacing test 2026-11-12: "it never followed me"): a target that moved
# more than the dead zone since the look before is acted on at once (no second look), and the
# head aims a little ahead of it, a constant-velocity lead from the last two centres, because the
# camera, the detector and the spring servo together lag about half a second.
MOVING_STEP = 0.08  # of the frame width between two looks: the target is walking, act now
LEAD_S = 0.5
LEAD_MAX = 0.2  # of the frame width: the lead never guesses further than this
WAIT_HINT_MAX_S = 20.0  # a lost follow waits at most this long on movement or a weak hint
STILL_FOR_SEARCH_S = 1.5  # still this long with no face: look for the face above the body
RELAX_AFTER_S = 90.0  # still this long: relax, head back to rest; the next move wakes it
FOLLOW_LOST_S = 2.0  # no face and no body this long: back to aiming (they may reappear)
GIVE_UP_S = 10.0  # nothing for this long: back to rest, no miss counted
BODY_HEAD_SHARE = 0.15  # the point to look at on a body without a face: this far down from its top

PERSON_GONE_S = 2.0  # no box this long while aiming: the person left the picture
BACKOFF_S = (60.0, 3 * 60.0, 600.0)  # after a miss on the same still person: 1, 3, 10 minutes
RETRY_MOVE = 0.15  # the box centre moved this share of the frame: a new try is worth it
MAX_ATTEMPTS = 3  # in ATTEMPTS_WINDOW_S
ATTEMPTS_WINDOW_S = 600.0
ATTEMPT_CAP_S = 12.0  # aiming and the face search together (following is open-ended)
SPEAKER_PERSON_FRESH_S = 15.0  # at listen start, turn toward a body seen this recently

# How long a move takes at these speeds (the servo is a spring: most of the way quickly, then
# a slow tail). Measured 2026-11-12 at speed 120: 60 degrees took about 2 s for two thirds and
# 6 s to settle; at 300 the spring is six times stiffer, so a 60 degree move settles in about
# 1.2 s and a small one in well under a second.
MOVE_BASE_S = 0.6
MOVE_S_PER_DEG = 0.01


@dataclass(frozen=True)
class PersonBox:
    """A person in the picture as shares of the frame: x, y, width, height, and the score."""

    x: float
    y: float
    w: float
    h: float
    score: float

    @property
    def centre_x(self) -> float:
        return self.x + self.w / 2

    @property
    def top(self) -> float:
        return self.y

    @property
    def area(self) -> float:
        return self.w * self.h


@dataclass(frozen=True)
class Move:
    yaw_deg: float  # absolute, left negative (as follow_pose has it)
    pitch_deg: float  # absolute, degrees up from the resting (level) pitch
    speed: int
    duration_s: float
    why: str


@dataclass(frozen=True)
class Action:
    """What the behavior does now: "move" (with `move`), "return" (back to rest), or "none"."""

    kind: str
    move: Move | None = None


NONE = Action("none")
RETURN = Action("return")

IDLE, AIMING, FACE_SEARCH, FOLLOW = "idle", "aiming", "face-search", "follow"


def choose_person(boxes: list[PersonBox], last: PersonBox | None = None) -> PersonBox | None:
    """The one person to follow: the largest box (the nearest). Two within 10 percent in area
    pick the one nearest the middle of the picture; while an attempt runs the earlier choice is
    kept when a box still overlaps where it was."""
    good = [b for b in boxes if b.score >= PERSON_SCORE]
    if not good:
        return None
    if last is not None:
        near = [b for b in good if abs(b.centre_x - last.centre_x) <= max(0.2, last.w)]
        if near:
            return max(near, key=lambda b: b.area)
    good.sort(key=lambda b: -b.area)
    best = good[0]
    ties = [b for b in good if b.area >= best.area * 0.9]
    return min(ties, key=lambda b: abs(b.centre_x - 0.5))


def yaw_error_deg(box: PersonBox) -> float:
    """How far off the picture's middle the person is, in head degrees, with the same
    camera-to-head mapping (span and sign) face following uses."""
    return (box.centre_x - 0.5) * FOLLOW_YAW_SPAN_DEG * FOLLOW_YAW_SIGN


def move_duration_s(degrees: float) -> float:
    return MOVE_BASE_S + MOVE_S_PER_DEG * abs(degrees)


class PersonTracker:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.stage = IDLE
        self.pose = (0.0, 0.0)  # yaw, pitch up from level, in degrees: the head's last command
        self.events: list[str] = []  # one plain line per stage change, drained by the behavior
        self._box_looks: list[tuple[float, bool]] = []  # (when, a good box was in the look)
        self._last_box: PersonBox | None = None
        self._last_box_at = float("-inf")
        self._target: PersonBox | None = None
        self._started_at = 0.0
        self._stage_at = 0.0
        self._moves = 0
        self._follow_moves = 0
        self._centred = 0
        self._judge_after = float("-inf")  # a look's frame must be newer than this to count
        self._poses: list[tuple[float, float]] = []
        self._pose_index = -1
        self._misses = 0
        self._last_miss_at = float("-inf")
        self._missed_box: PersonBox | None = None
        self._search_wait_until = float("-inf")  # no face search from follow before this
        self._pitch_before_search = 0.0
        self._pitch_before_aim = 0.0
        self._attempts: list[float] = []
        self._face_last_seen = float("-inf")
        # Following: the smoothed target, its speed, when it was last seen and last moved.
        self._track: tuple[float, float] | None = None  # smoothed (x, y)
        self._off_centre_looks = 0  # looks in a row with the target outside the dead zone
        self._just_found = False  # the first move after a face or body is found is immediate
        self._was_following = False  # aiming again after a follow lost sight: wait, not search
        self._lost_at = float("-inf")
        self._prev_target: tuple[float, float, float] | None = None  # x, y, when: for the lead
        self._track_at = float("-inf")
        self._still_since: float | None = None
        self._target_last_at = float("-inf")
        self._relaxed_at: tuple[float, float] | None = None  # where the person was when relaxed
        self.lag_samples: list[float] = []  # measured: how far off centre the target sat (shares)

    # -- what the behavior tells it -------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.stage != IDLE

    @property
    def following(self) -> bool:
        return self.stage == FOLLOW

    def note_pose(self, yaw_deg: float, pitch_deg: float) -> None:
        """The head was moved by someone else (a search pose, the turn toward a speaker, the
        return to rest): remember where it points, so the next move is relative to the truth."""
        self.pose = (float(yaw_deg), float(pitch_deg))

    def may_start(self, now: float) -> bool:
        """Not already busy, the back-off after a miss is over, and under the attempt cap."""
        if self.stage != IDLE:
            return False
        self._attempts = [t for t in self._attempts if now - t < ATTEMPTS_WINDOW_S]
        if len(self._attempts) >= MAX_ATTEMPTS:
            return False
        if self._misses == 0:
            return True
        wait = BACKOFF_S[min(self._misses, len(BACKOFF_S)) - 1]
        return now - self._last_miss_at >= wait

    def cancel(self, now: float, why: str) -> None:
        """Something more important (a rest, the night, a touch): stop, no miss counted."""
        if self.stage != IDLE:
            self.events.append(f"{self.stage} -> idle: {why} ({now - self._started_at:.1f} s)")
        self._to_idle()

    def _to_idle(self) -> None:
        self.stage = IDLE
        self._target = None
        self._track = None
        self._still_since = None

    # -- one look --------------------------------------------------------------------------------

    def observe(
        self,
        now: float,
        boxes: list[PersonBox],
        *,
        face_age: float | None,
        look_at: float | None,
        face_xy: tuple[float, float] | None = None,
        face_gone: bool | None = None,
        presence_hint: bool = False,
    ) -> Action:
        """Feed one look: the person boxes in it, how long ago a face was last seen and where,
        when its frame arrived, and whether something weaker (movement, a detector hint) says
        a person is still there. Returns what the head should do now."""
        face_fresh = face_age is not None and face_age <= FACE_FRESH_S
        if face_fresh:
            self._face_last_seen = now
        chosen = choose_person(boxes, self._target)
        if chosen is not None:
            self._last_box, self._last_box_at = chosen, now
            self._target = chosen if self.stage != IDLE else self._target
        self._box_looks.append((now, chosen is not None))
        self._box_looks = self._box_looks[-PERSON_WINDOW:]

        if self.stage == IDLE:
            if face_gone is None:
                face_gone = face_age is None or face_age > FACE_GONE_S
            return self._maybe_start(now, chosen, face_fresh, face_xy, face_gone)
        if look_at is not None and look_at < self._judge_after:
            return NONE  # that frame was taken before the head settled: not evidence
        if self.stage == FOLLOW:
            return self._follow(now, chosen, face_fresh, face_xy)
        # aiming or face-search
        if face_fresh:
            self._found(now)
            return self._follow(now, chosen, True, face_xy)
        if (
            self.stage == AIMING
            and not self._was_following
            and now - self._started_at > ATTEMPT_CAP_S
        ):
            return self._miss(now, "the attempt ran out of time")
        if chosen is None and now - self._last_box_at > PERSON_GONE_S:
            if presence_hint and now - self._lost_at < WAIT_HINT_MAX_S:
                self._target_last_at = now  # someone still seems to be there: keep waiting here
            if self.stage == AIMING and now - self._target_last_at > GIVE_UP_S:
                return self._lost(now, "nobody came back")
            if self.stage == AIMING and self._was_following:
                return NONE  # lost while following: wait where they were for them to come back
            if self.stage == AIMING and self.pose[1] > self._pitch_before_aim + 1.0:
                # The aim tilted up and the body dropped out of the picture below: the face is
                # above it, so look there; the head comes back down to the body if none shows.
                return self._begin_search(
                    now, "the body dropped below the picture after the tilt", self._pitch_before_aim
                )
            return self._lost(now, "the person left the picture")
        if self.stage == AIMING:
            return self._aim(now, chosen)
        return self._search(now, chosen)

    # -- starting --------------------------------------------------------------------------------

    def _maybe_start(
        self,
        now: float,
        chosen: PersonBox | None,
        face_fresh: bool,
        face_xy: tuple[float, float] | None,
        face_gone: bool,
    ) -> Action:
        where = (
            face_xy
            if face_fresh and face_xy is not None
            else (chosen.centre_x, chosen.top)
            if chosen is not None
            else None
        )
        if where is None:
            return NONE
        if self._relaxed_at is not None:
            if abs(where[0] - self._relaxed_at[0]) < RETRY_MOVE:
                return NONE  # relaxed on this person while they sit still; a move wakes it
            self._relaxed_at = None
        if face_fresh and face_xy is not None:
            if not self.may_start(now):
                return NONE
            self._attempts.append(now)
            self._started_at = self._stage_at = now
            self._moves = self._follow_moves = 0
            self._judge_after = float("-inf")
            self.stage = FOLLOW
            self._just_found = True
            self.events.append(f"face seen at x {face_xy[0]:.2f}, y {face_xy[1]:.2f} -> follow")
            return self._follow(now, chosen, True, face_xy)
        if chosen is None or not face_gone:
            return NONE
        seen = sum(1 for _, good in self._box_looks if good)
        if seen < PERSON_LOOKS:
            return NONE
        if self._missed_box is not None and (
            abs(chosen.centre_x - self._missed_box.centre_x) >= RETRY_MOVE
        ):
            self._misses = 0  # they moved: the earlier miss no longer counts
            self._missed_box = None
        if not self.may_start(now):
            return NONE
        return self.start(now, chosen, "seen")

    def start(self, now: float, box: PersonBox, how: str) -> Action:
        """Begin an attempt on this person (also used by the speaker turn and the find-me sweep,
        which already know where the person is)."""
        self._attempts.append(now)
        self._target = box
        self._last_box, self._last_box_at = box, now
        self._started_at = self._stage_at = now
        self._moves = self._follow_moves = 0
        self._centred = 0
        self._judge_after = float("-inf")
        self._track = None
        self._relaxed_at = None
        self._pitch_before_aim = self.pose[1]
        self._was_following = False
        self.stage = AIMING
        self.events.append(
            f"person {how} at x {box.centre_x:.2f}, box top {box.top:.2f}, score {box.score:.2f}"
            f" -> aiming"
        )
        return self._aim(now, box)

    # -- aiming and the face search ------------------------------------------------------------

    def _aim(self, now: float, box: PersonBox | None) -> Action:
        if box is None:
            return NONE  # no box in this look but the person was there a moment ago: wait
        self._target = box
        self._target_last_at = now
        error = yaw_error_deg(box)
        if abs(box.centre_x - 0.5) <= AIM_DEAD_ZONE:
            self._centred += 1
            if self._centred >= CENTRED_LOOKS:
                return self._begin_follow(now, "centred")
            return NONE
        self._centred = 0
        if self._moves >= AIM_MAX_MOVES or now - self._stage_at > AIM_TIMEOUT_S:
            return self._begin_follow(now, "roughly on the person")
        step = max(-AIM_MAX_STEP_DEG, min(AIM_MAX_STEP_DEG, error * AIM_GAIN))
        yaw = self.pose[0] + step
        pitch = self.pose[1]
        if box.top <= BOX_TOP_CUT:
            pitch = min(TILT_MAX_DEG, pitch + AIM_TILT_STEP_DEG)
        return self._move(now, yaw, pitch, AIM_SPEED, f"aim at x {box.centre_x:.2f}")

    def _begin_follow(self, now: float, why: str) -> Action:
        """Aimed: follow the body from here; the face search starts once they stand still."""
        self.events.append(
            f"aiming -> follow: {why} after {now - self._stage_at:.1f} s, {self._moves} move(s)"
        )
        self.stage = FOLLOW
        self._stage_at = now
        self._still_since = now  # standing still at the desk is the common case: search soon
        self._track = None
        return NONE

    def _begin_search(self, now: float, why: str, back_to: float | None = None) -> Action:
        self.events.append(f"{self.stage} -> face-search: {why} after {now - self._stage_at:.1f} s")
        self.stage = FACE_SEARCH
        self._stage_at = now
        yaw, pitch = self.pose
        # Where the body was: the head comes back to it when no face shows.
        self._pitch_before_search = pitch if back_to is None else back_to
        poses: list[tuple[float, float]] = []
        step = pitch
        while len(poses) < SEARCH_MAX_POSES - 2 and step < TILT_MAX_DEG:
            step = min(TILT_MAX_DEG, step + TILT_STEP_DEG)
            poses.append((yaw, step))
        top = poses[-1][1] if poses else pitch
        poses.append((yaw - SEARCH_PAN_DEG, top))
        poses.append((yaw + SEARCH_PAN_DEG, top))
        self._poses = poses[:SEARCH_MAX_POSES]
        self._pose_index = 0
        y, p = self._poses[0]
        return self._move(now, y, p, AIM_SPEED, "face-search tilt")

    def _search(self, now: float, box: PersonBox | None) -> Action:
        if now - self._stage_at > SEARCH_TIMEOUT_S:
            return self._search_missed(now, "no face after the search")
        # The look that reached here is fresh evidence for the current pose: no face in it.
        self._pose_index += 1
        if self._pose_index >= len(self._poses):
            return self._search_missed(now, "no face in any pose")
        yaw, pitch = self._poses[self._pose_index]
        if box is not None and abs(box.centre_x - 0.5) > 2 * AIM_DEAD_ZONE:
            # The person drifted: fold the correction into this pose.
            yaw = self.pose[0] + yaw_error_deg(box) * AIM_GAIN
            self._poses = [(yaw, p) for _, p in self._poses]
        return self._move(now, yaw, pitch, AIM_SPEED, "face-search pose")

    def _search_missed(self, now: float, why: str) -> Action:
        """No face above the body: keep following the body, and do not search again for a while
        (1, 3, 10 minutes) unless the person moves."""
        self._misses += 1
        self._last_miss_at = now
        self._missed_box = self._target
        wait = BACKOFF_S[min(self._misses, len(BACKOFF_S)) - 1]
        self._search_wait_until = now + wait
        self.events.append(
            f"face-search -> follow: {why} ({now - self._stage_at:.1f} s); following the body, "
            f"the next face search waits {wait:.0f} s unless the person moves"
        )
        self.stage = FOLLOW
        self._stage_at = now
        self._still_since = now
        # Back to the body's height: the search tilted the head above it.
        yaw, pitch = self.pose[0], self._pitch_before_search
        if abs(pitch - self.pose[1]) < 1.0:
            return NONE
        return self._move(now, yaw, pitch, FOLLOW_SPEED, "back to the body")

    # -- following -------------------------------------------------------------------------------

    def _follow(
        self,
        now: float,
        box: PersonBox | None,
        face_fresh: bool,
        face_xy: tuple[float, float] | None,
    ) -> Action:
        if face_fresh and face_xy is not None:
            target = face_xy
        elif box is not None:
            target = (box.centre_x, box.top + BODY_HEAD_SHARE * box.h)
        else:
            target = None
        if target is None:
            if now - self._target_last_at > FOLLOW_LOST_S:
                self.events.append(
                    f"follow -> aiming: lost sight for {now - self._target_last_at:.1f} s"
                )
                self.stage = AIMING
                self._stage_at = now
                self._moves = self._centred = 0
                self._started_at = now  # the attempt cap counts from here
                self._was_following = True
                self._lost_at = now
                self._pitch_before_aim = 0.0
                if self.pose[1] > 1.0:
                    # Back to level: a body that walked off is at the camera's own height, and a
                    # head left looking up sees only the ceiling (pacing test 2026-11-12).
                    return self._move(now, self.pose[0], 0.0, FOLLOW_SPEED, "lost: back to level")
            return NONE
        # Is the target walking? Compare with the look before (in the same head pose).
        moving = False
        lead = 0.0
        prev = self._prev_target
        if prev is not None and now > prev[2]:
            step = target[0] - prev[0]
            moving = abs(step) >= MOVING_STEP
            if moving:
                lead = max(-LEAD_MAX, min(LEAD_MAX, step / (now - prev[2]) * LEAD_S))
        self._prev_target = (target[0], target[1], now)
        # Smooth the measurement a little (one look is noisy at the box edges); not a walker.
        if self._track is not None and not moving:
            smoothed = (
                FOLLOW_SMOOTH * target[0] + (1 - FOLLOW_SMOOTH) * self._track[0],
                FOLLOW_SMOOTH * target[1] + (1 - FOLLOW_SMOOTH) * self._track[1],
            )
        else:
            smoothed = target
        self._track, self._track_at = smoothed, now
        self._target_last_at = now
        self.lag_samples.append(abs(target[0] - 0.5))
        self.lag_samples = self.lag_samples[-200:]
        error_x = smoothed[0] + lead - 0.5
        error_y = 0.5 - smoothed[1]
        yaw, pitch = self.pose
        move = False
        if abs(error_x) > AIM_DEAD_ZONE:
            step = max(
                -FOLLOW_MAX_STEP_DEG,
                min(
                    FOLLOW_MAX_STEP_DEG,
                    error_x * FOLLOW_YAW_SPAN_DEG * FOLLOW_YAW_SIGN * FOLLOW_GAIN,
                ),
            )
            yaw += step
            move = True
        if face_fresh and abs(error_y) > FOLLOW_PITCH_DEAD_ZONE:
            pitch = max(
                0.0,
                min(TILT_MAX_DEG, pitch + error_y * FOLLOW_PITCH_SPAN_DEG * FOLLOW_PITCH_GAIN),
            )
            move = abs(pitch - self.pose[1]) >= 1.0 or move
        if (
            move
            and not self._just_found
            and not moving
            and self._off_centre_looks + 1 < FOLLOW_CONFIRM_LOOKS
        ):
            self._off_centre_looks += 1
            return NONE  # one look off centre may be jitter: wait for the next before moving
        if not move:
            self._off_centre_looks = 0
            self._just_found = False  # centred at the find: a later step needs two looks
            # In the dead zone: hold. Standing still this long with no face: look for it above
            # the body; still for a long while: relax, and a step across the room wakes it.
            if self._still_since is None:
                self._still_since = now
            still_for = now - self._still_since
            if still_for >= RELAX_AFTER_S:
                self.events.append(
                    f"follow -> idle: still for {still_for:.0f} s, relaxing until they move"
                )
                self._relaxed_at = target
                self._to_idle()
                return RETURN
            if (
                not face_fresh
                and still_for >= STILL_FOR_SEARCH_S
                and now >= self._search_wait_until
                and now - self._face_last_seen > FACE_GONE_S
            ):
                return self._begin_search(now, "standing still with no face in view")
            return NONE
        self._still_since = None
        self._track = None  # the head moves: the next look's picture starts afresh
        self._prev_target = None
        self._off_centre_looks = 0
        self._just_found = False
        self._follow_moves += 1
        return self._move(
            now,
            yaw,
            pitch,
            FOLLOW_SPEED,
            f"follow the {'face' if face_fresh else 'body'} at x {target[0]:.2f}",
        )

    # -- outcomes ---------------------------------------------------------------------------------

    def _move(self, now: float, yaw: float, pitch: float, speed: int, why: str) -> Action:
        degrees = max(abs(yaw - self.pose[0]), abs(pitch - self.pose[1]))
        duration = move_duration_s(degrees)
        self.pose = (yaw, pitch)
        self._moves += 1 if self.stage == AIMING else 0
        self._judge_after = now + duration + AIM_SETTLE_S
        return Action("move", Move(yaw, pitch, speed, duration, why))

    def _found(self, now: float) -> None:
        self.events.append(
            f"{self.stage} -> follow: face found after {now - self._started_at:.1f} s, "
            f"{self._moves} aim move(s)"
        )
        self.stage = FOLLOW
        self._stage_at = now
        self._just_found = True
        self._misses = 0
        self._missed_box = None
        self._search_wait_until = float("-inf")
        self._still_since = None

    def _miss(self, now: float, why: str) -> Action:
        self._misses += 1
        self._last_miss_at = now
        self._missed_box = self._target
        wait = BACKOFF_S[min(self._misses, len(BACKOFF_S)) - 1]
        self.events.append(
            f"{self.stage} -> lost: {why} ({now - self._started_at:.1f} s); "
            f"the next try waits {wait:.0f} s unless the person moves"
        )
        self._to_idle()
        return RETURN

    def _lost(self, now: float, why: str) -> Action:
        self.events.append(f"{self.stage} -> lost: {why} ({now - self._started_at:.1f} s)")
        self._to_idle()
        return RETURN

    def drain_events(self) -> list[str]:
        events, self.events = self.events, []
        return events

    def follow_report(self) -> str | None:
        """One line of measured following: moves and how far off centre the target sat."""
        if not self.lag_samples:
            return None
        samples = sorted(self.lag_samples)
        median = samples[len(samples) // 2]
        moves, self._follow_moves, self.lag_samples = self._follow_moves, 0, []
        return (
            f"{moves} follow move(s); the target sat a median {median:.2f} "
            f"(at most {samples[-1]:.2f}) of the frame width off centre over {len(samples)} looks"
        )


__all__ = [
    "AIM_DEAD_ZONE",
    "AIM_GAIN",
    "AIM_MAX_STEP_DEG",
    "AIM_SPEED",
    "BACKOFF_S",
    "FACE_GONE_S",
    "FOLLOW_LOST_S",
    "FOLLOW_MAX_STEP_DEG",
    "FOLLOW_SPEED",
    "GIVE_UP_S",
    "PERSON_SCORE",
    "RELAX_AFTER_S",
    "SPEAKER_PERSON_FRESH_S",
    "TILT_MAX_DEG",
    "TILT_STEP_DEG",
    "Action",
    "Move",
    "PersonBox",
    "PersonTracker",
    "choose_person",
    "yaw_error_deg",
]
