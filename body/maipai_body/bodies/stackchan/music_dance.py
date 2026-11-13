"""The StackChan music dance: hear clear music, show a small "I like this", dance if it goes on.

Design: the StackChan dance note of 2026-11-13 (parts 2 and 3), owner request the same day. The
unit measures the room's sound (firmware patches 100 and 101, ``maipai_music_core.h``) and sends
one small ``music_feat`` event about once a second, only when the room is loud and the unit is
not speaking, listening or playing a sound. No audio leaves the unit. This module is the host
half: it reads those numbers, decides "clear music" with hysteresis, and runs the stages.

Every time and number here is an UNMEASURED design default; the logs below exist to tune them.

1. Detection: clear rhythmic music for ``detect_s`` (4 s) in a row (one missed or doubtful second
   is forgiven). "Clear music" means a steady beat (tempo 60 to 187 BPM with enough confidence
   for the sensitivity), a spectrum that is not flat noise, and none of the speech cues (a 3 to
   6 Hz rhythm in the loudness, many pauses). A TV theme or music under talk should score as
   speech or not at all.
2. The nod: one subtle "I like this": two small slow nods and a happy or a wink face for about
   3 s. No ring light. Once per music session.
3. The build-up: if the music is still clear ``nod_to_build_s`` (20 s) after the nod began, about
   10 s of the firmware's happy sway with a slow two-colour glow on the ring in the last 3 s
   (0.2 bright).
4. The dance: straight on, up to 20 s of the firmware keyframe dances (the head moves only inside
   the unit: it refuses more than 40 head calls a minute, patch 038) with the ring show. It is
   the little dance's machinery (dance.py ``DanceRunner`` with its own ``Plan``).
5. The end: 5 s without clear music, the 20 s cap, or any touch, turn, wake word, shake, tilt,
   picture, low battery, offline or estop (the runner's own checks). Then the ring goes dark and
   the head goes back to level.

Never annoying, as rules: off by default (``robot.dance.auto``); nothing at night, asleep, during
a turn, with the camera or live cue showing, in full quiet or muted, or while the emergency stop
is latched; at least ``MIN_GAP_S`` (10 min) after the last dance and ``NOD_GAP_S`` between nods;
at most 3 dances an hour and 10 a day (a nod needs room under those caps too, since it is the
first stage of a dance); the same music never starts a second session (the unit must hear
``Timing.rearm_quiet_s`` of quiet first). Battery: on battery a full dance needs
``FULL_BATTERY`` percent (40), from ``NOD_BATTERY`` (20) up to that only the nod, under 20 or
unknown nothing; while charging there is no battery gate (no battery cost; the design note's
question 3 recommendation, to be confirmed) but every other rule applies.

Not the ambient head gate: the nod and the dance are explicit behaviours behind an explicit
setting, so the 2026-10-20 "still while charging or at idle level still" rule for wandering does
not apply, the same as for the asked dance. They obey the situation gates above.

Measuring (while ``robot.dance.auto`` is on, or a test runs): one INFO line per stage change, one
per detection (tempo and confidence), one a minute (feature windows, music windows, false-start
candidates: a run of music-like windows that ended before ``detect_s``). ``music_test`` (a hub
device command) feeds scripted music-like numbers for a minute so the whole chain can be seen
without music; it obeys the safety gates but not the setting, the caps or the gaps, and counts
toward no cap.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from maipai_body.bodies.stackchan.dance import (
    GOLD,
    HAPPY_S,
    LIME,
    ROBOT_S,
    DanceSettings,
    DanceSituation,
    Plan,
    Rgb,
    _scaled,
    ring_frame,
)

logger = logging.getLogger("maipai_body.bodies.stackchan.music_dance")

LED_COUNT = 12

# ---------------------------------------------------------------- the numbers from the unit

MUSIC_FEAT_KIND = "music_feat"
MIN_BPM = 60
MAX_BPM = 187  # the firmware's lag range (patch 100)
MIN_LEVEL = 400  # RMS of channel 0; the unit already sends nothing under this


@dataclass(frozen=True)
class MusicFeat:
    """One second of the room, as the unit measured it (patch 100). All integers."""

    lv: int  # RMS level
    b: tuple[int, int, int, int]  # band shares, percent
    bpm: int  # tempo, 0 when no beat was found
    tc: int  # tempo confidence 0..100
    fl: int  # spectral flatness 0..100 (white noise 97, music 5 to 50)
    zc: int  # mean zero crossings per 20 ms
    zs: int  # their spread, percent
    mo: int  # share of the loudness' variance at 3 to 6 Hz, 0..100 (speech is high)
    ps: int  # share of near-silent 20 ms frames, 0..100
    on: int = 0  # onset strength
    muted: bool = False


def _int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def parse_music_feat(extra: Mapping[str, object] | None) -> MusicFeat | None:
    """The event's fields as a ``MusicFeat``, or None when a needed one is missing or not a
    number."""
    if not extra:
        return None
    needed = {}
    for key in ("lv", "bpm", "tc", "fl", "mo", "ps"):
        value = _int(extra.get(key))
        if value is None:
            return None
        needed[key] = value
    shares = tuple(_int(extra.get(f"b{i}")) or 0 for i in range(4))
    return MusicFeat(
        lv=needed["lv"],
        b=(shares[0], shares[1], shares[2], shares[3]),
        bpm=needed["bpm"],
        tc=needed["tc"],
        fl=needed["fl"],
        zc=_int(extra.get("zc")) or 0,
        zs=_int(extra.get("zs")) or 0,
        mo=needed["mo"],
        ps=needed["ps"],
        on=_int(extra.get("on")) or 0,
        muted=bool(extra.get("muted")),
    )


@dataclass(frozen=True)
class Sensitivity:
    tc_min: int  # the least tempo confidence that counts as a beat
    mo_max: int  # at or above this share at 3 to 6 Hz it is speech
    ps_max: int = 40  # at or above this share of pauses it is speech...
    ps_tc_free: int = 50  # ...unless the beat is this steady (a sparse click track)
    fl_max: int = (
        88  # at or above this flatness it is noise (white noise 97, a song across a room 47 to 85)
    )


# low wants a clearer beat; high takes a weaker one. Tuned 2026-11-13 on one real song at 1 m
# (tc 9 to 56, median 24).
SENSITIVITIES: dict[str, Sensitivity] = {
    "low": Sensitivity(tc_min=40, mo_max=40),
    "medium": Sensitivity(tc_min=20, mo_max=45),
    "high": Sensitivity(tc_min=14, mo_max=55),
}


@dataclass(frozen=True)
class Verdict:
    music: bool
    why: str  # exactly one reason code, including "music"


STEADY_TC_MIN = 8  # some tempo was found at all (a song measured 12 to 27 here)
TALKER_WINDOWS = 10  # the last seconds looked at for a person talking over the sound
TALKER_MIN_WINDOWS = 4
TALKER_SHARE = 0.4  # this share of speech-like seconds: a talker, not a song
TALKER_PS = 24  # a speech-like second: many near-silent frames...
TALKER_MO = 28  # ...or a strong 3 to 6 Hz loudness rhythm
STEADY_LEVEL = 800  # a song heard across a room measured 1000 to 1900
STEADY_MO_MAX = 32  # speech modulates at 3 to 6 Hz (45 to 60); songs measured 6 to 30
STEADY_PS_MAX = 20  # speech has pauses (45); songs measured 0 to 28
STEADY_FL_MAX = 97  # white noise is 97 and up


def _steady_sound(feat: MusicFeat) -> bool:
    """Loud, unbroken, not speech-like and not noise. Some songs give no steady tempo estimate
    (it wandered 60 to 250 BPM on a real one), so the beat bar alone would reject them."""
    return (
        feat.lv >= STEADY_LEVEL
        and feat.bpm > 0
        and feat.tc >= STEADY_TC_MIN
        and feat.mo < STEADY_MO_MAX
        and feat.ps < STEADY_PS_MAX
        and feat.fl < STEADY_FL_MAX
    )


def judge(feat: MusicFeat, sensitivity: str = "medium", *, relaxed: bool = False) -> Verdict:
    """Is this second clear rhythmic music? ``relaxed`` is for a stage that is already running (the
    unit's own servo noise and a long song's quiet bars must not end it): the bars are lowered."""
    sens = SENSITIVITIES.get(sensitivity, SENSITIVITIES["medium"])
    tc_min, mo_max, ps_max, fl_max = sens.tc_min, sens.mo_max, sens.ps_max, sens.fl_max
    if relaxed:
        tc_min = max(8, tc_min // 2)
        fl_max += 10  # a bright song measured flatness 88 to 99 while it danced
        mo_max += 10
        ps_max += 10
    if feat.muted:
        return Verdict(False, "self_hearing_blank")
    if feat.lv < MIN_LEVEL:
        return Verdict(False, "below_level_gate")
    if sensitivity != "low" and _steady_sound(feat):
        return Verdict(True, "music")  # loud, steady, not speech or noise: the tempo may wander
    if feat.tc < tc_min:
        return Verdict(False, "weak_beat")
    if feat.bpm == 0:
        return Verdict(False, "no_tempo")
    if not MIN_BPM <= feat.bpm <= MAX_BPM:
        return Verdict(False, "tempo_out_of_range")
    if feat.fl >= fl_max:
        return Verdict(False, "too_flat")
    if feat.mo >= mo_max:
        return Verdict(False, "speech_like_modulation")
    if feat.ps >= ps_max and feat.tc < sens.ps_tc_free:
        return Verdict(False, "speech_like_pauses")
    return Verdict(True, "music")


# ---------------------------------------------------------------- timing and the plan


@dataclass(frozen=True)
class Timing:
    detect_s: float = 4.0  # clear music this long starts the nod
    gap_s: float = 2.5  # one missed or doubtful second between music seconds is forgiven
    nod_to_build_s: float = 20.0  # from the nod's start to the build-up
    end_silence_s: float = 9.0  # no clear music this long ends a running dance
    rearm_quiet_s: float = 10.0  # quiet this long before another session can begin
    session_gap_s: float = 60.0  # a song change: gaps under this keep the music session going
    break_s: float = 90.0  # the slow mood between dance blocks: a gentle sway, not a stop
    block_usb_s: float = 300.0  # one dance block on USB power or charging
    block_battery_s: float = 120.0  # one dance block on battery
    nod_s: float = 3.0  # the nod's face stays this long


NORMAL = Timing()
# for music_test with {"fast": true}: the same chain in about 40 s
FAST = Timing(
    detect_s=2.0,
    nod_to_build_s=6.0,
    end_silence_s=4.0,
    rearm_quiet_s=4.0,
    session_gap_s=8.0,
    break_s=6.0,
    block_usb_s=40.0,
    block_battery_s=40.0,
)

MIN_GAP_S = 120.0  # after the end of a dance (and so before the next nod)
NOD_GAP_S = 120.0  # between two nods
FULL_BATTERY = 40  # on battery: a full dance from this percent
NOD_BATTERY = 20  # on battery: only the nod from this percent, nothing under it
TEST_S = 60.0  # how long music_test feeds music-like seconds

GAP_FACE_S = 0.3
BUILD_S = 2 * HAPPY_S + GAP_FACE_S + 1.0  # 9.7 s: sway, wink, sway, a held beat
DANCE_S = 20.0
TOTAL_S = BUILD_S + DANCE_S
GLOW_FROM_S = BUILD_S - 3.0  # the first light, in the last 3 s of the build-up
GLOW_LEVEL = 0.4  # times the show's 0.5 brightness: 0.2
SHOW_PHASE_S = 6.7  # each ring pattern of the dance runs this long

_BUILD_AND_DANCE: tuple[tuple[float, str, str], ...] = (
    # the build-up: the firmware's happy sway twice, a wink between, a held beat
    (0.0, "face", "happy"),
    (0.0, "dance", "happy"),
    (HAPPY_S, "face", "happy"),
    (HAPPY_S + GAP_FACE_S, "dance", "happy"),
    (2 * HAPPY_S + GAP_FACE_S, "face", "happy"),
    # the dance: stiff turns and sways with the faces of the little dance
    (BUILD_S, "dance", "robot"),
    (BUILD_S + ROBOT_S, "face", "surprised"),
    (BUILD_S + ROBOT_S + GAP_FACE_S, "face", "happy"),
    (BUILD_S + ROBOT_S + GAP_FACE_S, "dance", "happy"),
    (BUILD_S + ROBOT_S + GAP_FACE_S + HAPPY_S, "face", "happy"),
    (BUILD_S + ROBOT_S + 2 * GAP_FACE_S + HAPPY_S, "dance", "robot"),
    (BUILD_S + 2 * ROBOT_S + 2 * GAP_FACE_S + HAPPY_S, "face", "happy"),
    (BUILD_S + 2 * ROBOT_S + 2 * GAP_FACE_S + HAPPY_S, "dance", "happy"),  # cut at the cap
)


def glow_frame(tick: int) -> list[Rgb]:
    """The build-up's ring: gold and lime in alternating pixels that swap every second tick, at
    0.2 brightness. Always two colours, always moving."""
    first, second = (GOLD, LIME) if (tick // 2) % 2 == 0 else (LIME, GOLD)
    return [_scaled(first if i % 2 == 0 else second, GLOW_LEVEL) for i in range(LED_COUNT)]


def _ring(tick: int, t_s: float) -> list[Rgb] | None:
    if t_s < GLOW_FROM_S:
        return None  # dark: the build-up is a head and face thing until the glow
    if t_s < BUILD_S:
        return glow_frame(tick)
    return ring_frame(tick, int((t_s - BUILD_S) // SHOW_PHASE_S) % 3)


AUTO_PLAN = Plan(_BUILD_AND_DANCE, TOTAL_S, _ring)
# the dance rounds after the first one of a cycle: the dance part only, the same ring show
_DANCE_ONLY = tuple(
    (at - BUILD_S, action, name) for at, action, name in _BUILD_AND_DANCE if at >= BUILD_S
)
DANCE_PLAN = Plan(
    _DANCE_ONLY, DANCE_S, lambda tick, t_s: ring_frame(tick, int(t_s // SHOW_PHASE_S) % 3)
)
# the slow mood: the firmware's gentle happy sway only, one happy face, no ring show
CALM_PLAN = Plan(((0.0, "face", "happy"), (0.0, "dance", "happy")), DANCE_S, lambda tick, t_s: None)

# ---------------------------------------------------------------- the controller

NodFn = Callable[[str, Callable[[], bool]], object]  # (face, cancelled) -> blocks until done


@dataclass
class MusicDanceHooks:
    """The robot side of the music dance, all injected (a test passes recorders)."""

    request_dance: Callable[[], tuple[bool, str]]  # starts the build-up and dance: (started, why)
    stop_dance: Callable[[str], object]
    dance_running: Callable[[], bool]
    nod: NodFn  # the small nod with a face; blocks, runs on its own thread
    restore_face: Callable[[], object]  # the idle face again
    situation: Callable[[], DanceSituation]
    notes: Callable[[int], object] | None = None  # music notes on the face: 0 hides, 1 nod, 3 dance


class MusicDance:
    """Decides "music" from the unit's numbers and runs the stages. Pure but for its hooks: the
    clock
    is passed in (``feed`` and ``tick``), so a test drives it with a scripted stream."""

    def __init__(
        self,
        hooks: MusicDanceHooks,
        settings: DanceSettings,
        *,
        spawn: Callable[[Callable[[], None]], object] | None = None,
        choose_face: Callable[[], str] | None = None,
        timing: Timing = NORMAL,
    ) -> None:
        self._hooks = hooks
        self.settings = settings
        self._spawn = spawn or self._thread
        self._choose_face = choose_face or (lambda: "happy")
        self._timing = timing
        self._normal_timing = timing
        self._lock = threading.RLock()
        self.state = "idle"  # idle | nod | watch | show | break | spent
        self.plan = "full"  # the next dance request: "full" (build-up and dance), "dance" or "calm"
        self._calm_at = float("-inf")
        self._cycle = 0
        self._talk: deque[bool] = deque(maxlen=TALKER_WINDOWS)
        self._notes_at = float("-inf")
        self._now = 0.0
        self._block_start = float("-inf")
        self._break_at = float("-inf")
        self._run_start: float | None = None
        self._last_pos: float | None = None
        self._run_len_pos = 0
        self._nod_at = float("-inf")
        self._nod_cancel = False
        self._last_dance_end = float("-inf")
        self._last_nod = float("-inf")
        self._test_until = -1.0
        self._test_next = 0.0
        self._session_test = False  # the running session began in a test: it ends on its own
        self._dance_started_at = float("-inf")
        # per-minute stats
        self._minute_at: float | None = None
        self._windows = 0
        self._music_windows = 0
        self._false_starts = 0
        self._reason_counts: dict[str, int] = {}
        self._feature_values: dict[str, list[int]] = {}
        self._last_reject_log = float("-inf")
        self.last_detection = ""

    # -- inputs

    @property
    def testing(self) -> bool:
        return self._test_until > 0

    def _active(self) -> bool:
        return self.settings.enabled and (self.settings.auto or self.testing or self._session_test)

    def feed(self, feat: MusicFeat, now: float) -> None:
        """One second of the room from the unit. Ignored (not even logged) while the music dance is
        off. A test's own scripted seconds come through here too."""
        with self._lock:
            self._now = now
            if not self._active():
                return
            self._count_minute(now)
            relaxed = self.state in ("nod", "watch", "show", "calm", "break")
            verdict = judge(feat, self.settings.auto_sensitivity, relaxed=relaxed)
            self._talk.append(feat.ps >= TALKER_PS or feat.mo >= TALKER_MO)
            if verdict.music and self._talker_over():
                verdict = Verdict(False, "talker_over_music")
            self._windows += 1
            self._reason_counts[verdict.why] = self._reason_counts.get(verdict.why, 0) + 1
            for name, value in self._features(feat).items():
                self._feature_values.setdefault(name, []).append(value)
            if verdict.music:
                self._music_windows += 1
                self._positive(feat, now)
            else:
                self._negative(now)
                if feat.lv >= MIN_LEVEL and now - self._last_reject_log >= 5.0:
                    self._last_reject_log = now
                    logger.info(
                        "StackChan music window rejected: reason=%s %s",
                        verdict.why,
                        self._feature_text(feat),
                    )
            self._advance(now, feat if verdict.music else None)

    def _talker_over(self) -> bool:
        """Someone is talking over the sound (a video with a speaker and background music): a
        stretch of seconds that are mostly speech-like is not a song, even when a beat shows."""
        if len(self._talk) < TALKER_MIN_WINDOWS:
            return False
        return sum(self._talk) / len(self._talk) >= TALKER_SHARE

    def tick(self, now: float) -> None:
        """Time passing: a music session ends, a running dance is checked, a test feeds its
        seconds."""
        with self._lock:
            self._now = now
            if self.testing:
                self._feed_test(now)
            if not self._active():
                if self.state in ("nod", "watch", "show"):
                    self._abort(now, "the setting is off")
                elif self.state != "idle":
                    self.state = "idle"
                return
            self._count_minute(now)
            self._advance(now, None)

    def on_events(self, events: object, now: float) -> None:
        """The unit's touch and shake events: a touch or shake in the nod or the wait ends the
        session
        (the running dance's own touch handling is the runner's)."""
        if self.state not in ("nod", "watch"):
            return
        if now - self._nod_at < 1.5:
            return  # the nod's own motion
        for event in events if isinstance(events, (list, tuple)) else []:
            kind = getattr(event, "kind", None)
            if kind in ("head_touch", "head_swipe_forward", "head_swipe_back", "shake"):
                with self._lock:
                    self._abort(now, "a touch" if kind != "shake" else "a shake")
                return

    # -- music tracking

    def _positive(self, feat: MusicFeat, now: float) -> None:
        if self._last_pos is None or now - self._last_pos > self._timing.gap_s:
            self._end_run(now)
            self._run_start = now
            self._run_len_pos = 0
        self._last_pos = now
        self._run_len_pos += 1
        self.last_detection = f"tempo {feat.bpm} bpm, confidence {feat.tc}%"

    def _negative(self, now: float) -> None:
        if self._last_pos is not None and now - self._last_pos > self._timing.gap_s:
            self._end_run(now)

    def _end_run(self, now: float) -> None:
        """A run of music-like seconds is over; one that never reached the nod is a false-start
        candidate (two seconds or more of it, so a single stray second is not counted)."""
        if (
            self._run_start is not None
            and self._last_pos is not None
            and self.state == "idle"
            and self._run_len_pos >= 2
            and self._last_pos - self._run_start < self._timing.detect_s
        ):
            self._false_starts += 1
        self._run_start = None

    def _music_for(self, now: float) -> float:
        """Seconds of unbroken clear music up to the last positive second (0 when it is gone)."""
        if self._run_start is None or self._last_pos is None:
            return 0.0
        if now - self._last_pos > self._timing.gap_s:
            return 0.0
        return self._last_pos - self._run_start

    def _music_gone(self, now: float) -> bool:
        """The music dipped: no clear second for the end-silence time (a round stops)."""
        return self._last_pos is None or now - self._last_pos >= self._timing.end_silence_s

    def _session_over(self, now: float) -> bool:
        """The music session is over: no clear second for the session gap (a song change is not)."""
        return self._last_pos is None or now - self._last_pos >= self._timing.session_gap_s

    # -- the stages

    def _advance(self, now: float, positive: MusicFeat | None) -> None:
        t = self._timing
        if self.state == "idle":
            if self._run_start is not None and (
                self._last_pos is None or now - self._last_pos > t.gap_s
            ):
                self._end_run(now)
            if positive is not None and self._music_for(now) >= t.detect_s:
                logger.info(
                    "StackChan music: detected clear music for %.0f s (%s)",
                    self._music_for(now),
                    self.last_detection,
                )
                self._try_nod(now)
        elif self.state == "nod":
            if now - self._nod_at >= t.nod_s:
                self._set_state("watch", "the nod is done; waiting to see if the music goes on")
                self._hooks.restore_face()
            self._check_interrupt(now)
        elif self.state == "watch":
            if self._check_interrupt(now):
                return
            if self._music_gone(now):
                self._set_state("spent", "the music stopped before the build-up")
            elif now - self._nod_at >= t.nod_to_build_s and positive is not None:
                self._try_dance(now)
        elif self.state == "show":
            self._show(now)
        elif self.state == "calm":
            self._calm(now, positive)
        elif self.state == "break":
            self._rest(now, positive)
        elif self.state == "spent":
            if self._last_pos is None or now - self._last_pos >= t.rearm_quiet_s:
                self._set_state("idle", "quiet again; ready for the next song")
                self._run_start = None

    def _notes(self, count: int, now: float) -> None:
        """Music notes on the face (the unit hides them itself 30 s after the last call)."""
        hook = self._hooks.notes
        if hook is None:
            return
        self._notes_at = now
        try:
            hook(count)
        except Exception:
            logger.debug("StackChan music notes call failed", exc_info=True)

    def _block_s(self) -> float:
        sit = self._hooks.situation()
        return self._timing.block_usb_s if sit.charging is True else self._timing.block_battery_s

    def _show(self, now: float) -> None:
        """A dance block: rounds of dancing while the music goes on, then a break."""
        sit = self._hooks.situation()
        if self._hooks.dance_running():
            if sit.muted or sit.full_quiet == "muted":
                self._hooks.stop_dance("muted")
            elif self._music_gone(now):
                self._hooks.stop_dance("music ended")
            elif now - self._notes_at >= 10.0:
                self._notes(3, now)  # keep the notes hopping while the dance goes on
            return
        # a round just ended (or was stopped): what next?
        if self._check_interrupt(now):
            self._dance_over(now)
        elif self._session_test or self._session_over(now):
            self._dance_over(now)
        elif self._music_gone(now):
            logger.info("StackChan music: cycle %d (paused: the music dipped)", self._cycle)
            self._break_at = now
            self._set_state("break", "no music for a moment: not dancing")
        elif now - self._block_start >= self._block_s():
            why, nod_only = self._gate(now, for_nod=False)
            if why is not None and not nod_only:
                self._dance_over(now)
                return
            logger.info("StackChan music: cycle %d (slow mood)", self._cycle)
            self._calm_at = now
            self._set_state("calm", "the slow mood between dance blocks")
            self._calm_round(now)
        else:
            why, nod_only = self._gate(now, for_nod=False)
            if why is not None or nod_only:
                self._dance_over(now)
                return
            self.plan = "dance"
            started, refused = self._hooks.request_dance()
            if not started:
                self._dance_over(now)
                return
            logger.info("StackChan music: cycle %d (dance round, music still going)", self._cycle)

    def _calm_round(self, now: float) -> None:
        """A gentle sway round: the slow mood keeps dancing, only slowly and without the show."""
        self.plan = "calm"
        started, refused = self._hooks.request_dance()
        if not started:
            logger.info("StackChan music: no slow mood round (%s)", refused or "refused")

    def _calm(self, now: float, positive: MusicFeat | None) -> None:
        """The slow mood: the sway goes on for the break time, then the slow start again. It only
        stops when the music is gone, the unit is paused or something else interrupts."""
        running = self._hooks.dance_running()
        if self._check_interrupt(now):
            self._dance_over(now)
        elif self._session_test or self._session_over(now):
            self._dance_over(now)
        elif self._music_gone(now):
            if running:
                self._hooks.stop_dance("music dipped")
            self._break_at = now
            self._set_state("break", "no music for a moment: not dancing")
        elif now - self._calm_at >= self._timing.break_s and positive is not None:
            if running:
                self._hooks.stop_dance("the next dance block")
            self._try_dance(now, new_cycle=True)
        elif not running:
            self._calm_round(now)
        elif now - self._notes_at >= 10.0:
            self._notes(1, now)

    def _rest(self, now: float, positive: MusicFeat | None) -> None:
        """No music for a moment (a gap inside the session): not dancing; it starts again with the
        slow start as soon as clear music returns."""
        if self._check_interrupt(now) or self._session_over(now):
            self._dance_over(now)
        elif positive is not None:
            self._try_dance(now, new_cycle=True)

    def _gate(self, now: float, *, for_nod: bool) -> tuple[str | None, bool]:
        """(reason it may not, True when only the nod is allowed)."""
        sit = self._hooks.situation()
        if sit.muted or sit.full_quiet == "muted":
            return "muted", False
        if sit.full_quiet:
            return "full quiet", False
        if sit.estop:
            return "the emergency stop is latched", False
        if not sit.connected or sit.offline:
            return "the unit is offline", False
        if not sit.upright:
            return "the unit is not upright", False
        if sit.camera_cue or sit.live_cue:
            return "a camera or live cue is showing", False
        if sit.in_turn:
            return "a turn is on", False
        if not sit.awake:
            return "the unit is asleep", False
        if sit.night:
            return "it is night", False
        nod_only = False
        if sit.charging is not True:
            if sit.battery_percent is None:
                return "the battery level is unknown", False
            if sit.battery_percent < NOD_BATTERY or sit.battery_low:
                return f"battery {sit.battery_percent}%", False
            nod_only = sit.battery_percent < FULL_BATTERY
        if for_nod and not self.testing:
            if now - self._last_dance_end < MIN_GAP_S:
                return "a dance ended less than 2 minutes ago", False
            if now - self._last_nod < NOD_GAP_S:
                return "a nod was less than 2 minutes ago", False
        return None, nod_only

    def _try_nod(self, now: float) -> None:
        why, _ = self._gate(now, for_nod=True)
        if why is not None:
            self._set_state("spent", f"no nod: {why}")
            return
        face = self._choose_face()
        self._session_test = self.testing
        self._nod_at = now
        if not self.testing:
            self._last_nod = now
        self._nod_cancel = False
        self._set_state("nod", f"the nod (face {face}, no ring light)")
        self._spawn(lambda: self._do_nod(face))

    def _do_nod(self, face: str) -> None:
        try:
            self._hooks.nod(face, lambda: self._nod_cancel)
        except Exception:
            logger.warning("StackChan music nod failed", exc_info=True)

    def _try_dance(self, now: float, *, new_cycle: bool = False) -> None:
        why, nod_only = self._gate(now, for_nod=False)
        if why is None and nod_only:
            why = "battery under 40% and not charging: the nod only"
        if why is not None:
            if new_cycle and (nod_only or why.startswith("battery")):
                self._break_at = now  # try again after another break
                return
            self._set_state("spent", f"no dance: {why}")
            return
        self.plan = "full"  # every cycle starts with the build-up (the slow start)
        started, refused = self._hooks.request_dance()
        if not started:
            self._set_state("spent", f"no dance: {refused or 'the dance runner refused'}")
            return
        self._cycle += 1
        self._dance_started_at = now
        self._block_start = now
        logger.info("StackChan music: cycle %d (slow start, then the dance)", self._cycle)
        self._set_state("show", "the build-up and the dance")

    def _dance_over(self, now: float) -> None:
        if not self._session_test:
            self._last_dance_end = now
        self._set_state("spent", "the dance is over")

    def _check_interrupt(self, now: float) -> bool:
        sit = self._hooks.situation()
        why = None
        if sit.estop:
            why = "the emergency stop"
        elif sit.in_turn or sit.live_cue:
            why = "a turn"
        elif not sit.upright:
            why = "a tilt"
        elif sit.camera_cue:
            why = "a picture"
        elif not sit.connected or sit.offline:
            why = "offline"
        elif sit.muted or sit.full_quiet == "muted":
            why = "muted"
        elif sit.full_quiet:
            why = "full quiet"
        elif sit.night:
            why = "night"
        elif not sit.awake:
            why = "sleep"
        if why is None:
            return False
        self._abort(now, why)
        return True

    def _abort(self, now: float, why: str) -> None:
        self._nod_cancel = True
        if self.state == "show":
            self._hooks.stop_dance(why)
            return
        if self.state in ("nod", "watch", "calm", "break"):
            self._set_state("spent", why if why == "the setting is off" else f"ended by {why}")

    def _set_state(self, state: str, why: str) -> None:
        if state == self.state:
            return
        logger.info("StackChan music: stage %s -> %s (%s)", self.state, state, why)
        self.state = state
        if state == "idle":
            self._session_test = False
        self._notes({"nod": 1, "show": 3, "calm": 1}.get(state, 0), self._now)

    # -- stats

    def _count_minute(self, now: float) -> None:
        if self._minute_at is None:
            self._minute_at = now
            return
        if now - self._minute_at < 60.0:
            return
        if self._windows:
            counts = ",".join(f"{k}:{v}" for k, v in sorted(self._reason_counts.items()))
            ranges = " ".join(
                f"{k}={self._summary(v)}" for k, v in self._feature_values.items() if v
            )
            line = (
                f"StackChan music minute: n={self._windows} mus={self._music_windows} "
                f"false={self._false_starts} stage={self.state} why[{counts}] {ranges}"
            )[:400]
            logger.info("%s", line)
        else:
            logger.debug("StackChan music minute: n=0 stage=%s", self.state)
        self._minute_at = now
        self._windows = self._music_windows = self._false_starts = 0
        self._reason_counts.clear()
        self._feature_values.clear()

    @staticmethod
    def _features(feat: MusicFeat) -> dict[str, int]:
        return {
            "lv": feat.lv,
            "b0": feat.b[0],
            "b1": feat.b[1],
            "b2": feat.b[2],
            "b3": feat.b[3],
            "on": feat.on,
            "bpm": feat.bpm,
            "tc": feat.tc,
            "fl": feat.fl,
            "zc": feat.zc,
            "zs": feat.zs,
            "mo": feat.mo,
            "ps": feat.ps,
        }

    @staticmethod
    def _summary(values: list[int]) -> str:
        ordered = sorted(values)
        n = len(ordered)
        median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) // 2
        return f"{ordered[0]}/{median}/{ordered[-1]}"

    @classmethod
    def _feature_text(cls, feat: MusicFeat) -> str:
        return " ".join(f"{key}={value}" for key, value in cls._features(feat).items())

    # -- the test

    def start_test(self, now: float, *, fast: bool = False) -> tuple[bool, str]:
        """``music_test``: feed music-like seconds for a minute. The safety gates still apply."""
        with self._lock:
            if self.settings.enabled is False:
                return False, "robot.dance.enabled is off"
            if self.testing:
                return False, "a music test is already running"
            if self.state in ("nod", "watch", "show"):
                return False, "a music session is already running"
            why, _ = self._gate(now, for_nod=False)
            if why is not None:
                logger.info("StackChan music test refused: %s", why)
                return False, why
            self._timing = FAST if fast else self._normal_timing
            self._test_until = now + (30.0 if fast else TEST_S)
            self._test_next = now
            self.state = "idle"
            self._run_start = self._last_pos = None
            logger.info("StackChan music test started (%s)", "fast" if fast else "normal")
            return True, ""

    def _feed_test(self, now: float) -> None:
        if now >= self._test_until:
            self._test_until = -1.0
            self._timing = self._normal_timing
            logger.info("StackChan music test: the scripted music has stopped")
            return
        while self._test_next <= now:
            self._test_next += 1.0
            self.feed(TEST_FEAT, now)

    # -- plumbing

    @staticmethod
    def _thread(target: Callable[[], None]) -> threading.Thread:
        thread = threading.Thread(target=target, name="stackchan-music-nod", daemon=True)
        thread.start()
        return thread


TEST_FEAT = MusicFeat(lv=2400, b=(40, 35, 18, 7), bpm=120, tc=80, fl=12, zc=15, zs=80, mo=15, ps=3)


def nod_steps(centre_pitch: int, speed: int) -> list[tuple[int, int, int, float]]:
    """The nod as (yaw, pitch, speed, pause after): two small slow nods of 8 degrees, then level."""
    steps: list[tuple[int, int, int, float]] = []
    for _ in range(2):
        steps.append((0, centre_pitch + 8, speed, 0.55))
        steps.append((0, centre_pitch, speed, 0.55))
    return steps


__all__ = [
    "AUTO_PLAN",
    "CALM_PLAN",
    "DANCE_PLAN",
    "FAST",
    "NORMAL",
    "MusicDance",
    "MusicDanceHooks",
    "MusicFeat",
    "Timing",
    "Verdict",
    "glow_frame",
    "judge",
    "nod_steps",
    "parse_music_feat",
]
