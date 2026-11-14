"""The StackChan's own sounds, the host side (firmware patches 115 to 118).

The unit owns the earcons: seven new ones in one soft-bell family (rising for good news, falling for
bad) are in its firmware, beside the five tones it always had. It plays the right one itself for
what only it sees (the charger, the link, first setup) and says a local clip when the wake
word fires with no link at all (tier 2 of the offline voice). This module is for what only the
host knows:

* ``play`` asks the unit to play one sound by name (``self.audio.play_sound``). The unit refuses it
  too, with the same rules, so a stale host cannot make it loud at night;
* the low battery earcon, then the spoken line "My battery is low. Please plug me in." once per
  crossing (the line by day only, the earcon at night too);
* the camera shutter when the camera cue goes up (a picture is being taken for Home or a person), at
  night too: it is a privacy cue, refused only by the hard mute;
* the error earcon before the spoken apology, the dance start chime, and the ``sound_test`` command
  Settings uses to play every sound in turn;
* the policy the unit applies on its own (``self.audio.set_sound_policy``): sounds on, sounds at
  night, the hard mute, the household quiet hours as minutes of the day (so the unit still keeps
  them with Home down) and "it is night now" from the light sensor.

Rules (owner, 2026-11-13): every sound follows the volume setting; quiet hours and the sensor night
silence everything except safety and privacy cues; nothing sounds for things that happen constantly.
``robot.sounds.enabled`` (default on) switches the event sounds off, ``robot.sounds.night`` (default
off) lets them play at night too; ``robot.muted`` and ``robot.quiet`` (read when Home sends them)
silence every sound, a picture's shutter included.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from maipai_body.bodies.stackchan.activity import log_activity
from maipai_body.settings_keys import (
    MUTED_KEY,
    QUIET_KEY,
    SOUNDS_ENABLED_KEY,
    SOUNDS_NIGHT_KEY,
)

logger = logging.getLogger("maipai_body.bodies.stackchan.sounds")

# The firmware's fixed list, in its order (maipai_sounds_core.h, patch 115; a test keeps them
# equal).
EARCONS = (
    "needs_you",
    "plug_in",
    "charged",
    "unplug",
    "offline",
    "goodbye",
    "shutter",
    "success",
    "popup",
    "vibration",
    "exclamation",
    "low_battery",
)
# Seconds each one lasts: the self-test waits this long before the next (the new seven are read from
# the rendered files by a test).
SECONDS = {
    "needs_you": 0.80,
    "plug_in": 0.46,
    "charged": 0.88,
    "unplug": 0.48,
    "offline": 0.72,
    "goodbye": 0.98,
    "shutter": 0.42,
    "success": 1.03,
    "popup": 0.48,
    "vibration": 0.79,
    "exclamation": 0.89,
    "low_battery": 1.02,
}
# Cues that may sound at night (the firmware's ms_night_ok): a picture, the power key, a low battery
# and an error (the earcon only), the tones that answer a person who is there, and the setup
# cue when the unit cannot work without a person (``urgent``).
NIGHT_OK = frozenset({"shutter", "goodbye", "low_battery", "exclamation", "popup", "vibration"})
# Cues that survive "sounds off" (the firmware's ms_safety): a picture and the urgent setup cue.
SAFETY = frozenset({"shutter"})

# The chime policy (owner 2026-11-14: "this is not something to chime for"; see "When it may
# chime" in docs/dev/stackchan-sounds-2026-11-13.md). A host-initiated cue sounds only when a
# person must notice it or it just changed because of them, never for something the robot chose
# to do by itself: no chime for dancing, music, song naming, face changes, idle looks,
# reconnects, retries or update checks. Every host play goes through ``SoundService.play``, which
# checks this list, a minimum gap per cue and a daily cap.
CHIME_ALLOWED = frozenset(
    {
        "needs_you",  # a person must act or decide
        "plug_in",  # power events a person caused
        "unplug",
        "charged",
        "low_battery",
        "shutter",  # a picture was taken
        "goodbye",  # shutdown
        "exclamation",  # a failure they must know about, after an action they asked for
    }
)
CHIME_GAP_S = 60.0  # the least time between two chimes of one cue, however often the event flaps
CHIME_GAP_BY_CUE = {"shutter": 2.0}  # one click per picture
CHIME_DAILY_CAP = 20  # chimes of one cue in 24 hours
CHIME_DAILY_CAP_BY_CUE = {"shutter": 500}
DAY_S = 24 * 3600.0

LOW_BATTERY_LINE = "My battery is low. Please plug me in."
SPEAK_FOR_S = 30.0  # keep trying to say the line while a turn is busy, then give up
SHUTTER_GAP_S = 2.0  # one click per picture, however the cue flaps
POLICY_EVERY_S = 300.0  # the unit keeps its policy in flash; this only repairs a missed push
# Owner 2026-11-14, twice ("make those beeps go away", "just remove the tone"): until the beeping
# source is named by the activity log below, the unit is told every sound is muted, so nothing it
# gates can play (the shutter and the low battery earcon included). Set False to restore the normal
# policy (enabled, night and mute follow the settings).
SILENCE_UNIT_SOUNDS = True
# The firmware that fixes the beeping at its root (image 1, 2026-11-14: the charger reading, the
# per-cue gap, the stock tones through the gate) reports this version or a later one in its `fw`
# event. From then on the forced mute above is dropped and the normal policy is pushed (shutter,
# low battery, needs_you, goodbye... per the chime rules); older firmware keeps the forced mute.
FIRMWARE_RESTORES_SOUNDS_FROM = (0, 2, 102)
SILENCED_POLICY_EVERY_S = (
    30.0  # while silenced the policy is repeated this often, so a reboot cannot undo it
)
INFO_POLL_S = 60.0  # the unit's own play counters are logged about once a minute
PUSH_RETRY_S = 5.0  # after a failed push (the unit is away) wait this long before trying again
DANCE_QUIET_AFTER_S = 30.0  # event sounds stay off this long after a music session ends


@dataclass(frozen=True)
class PlayResult:
    ok: bool
    # muted | night | disabled | unknown_sound | not_allowed | rate_limited | daily_cap |
    # unreachable | unsupported | missing
    reason: str = ""


def _parse(result: object) -> dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)
    if isinstance(result, (str, bytes)):
        try:
            parsed = json.loads(result)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _inline(job: Callable[[], None]) -> None:
    job()


class _Worker:
    """One thread that runs device calls in order, so no caller (a camera cue, a battery edge, the
    turn's event loop) ever waits on the unit."""

    def __init__(self) -> None:
        self._jobs: queue.Queue[Callable[[], None]] = queue.Queue(maxsize=32)
        self._thread = threading.Thread(target=self._run, name="stackchan-sounds", daemon=True)
        self._started = False
        self._lock = threading.Lock()

    def submit(self, job: Callable[[], None]) -> None:
        with self._lock:
            if not self._started:
                self._started = True
                self._thread.start()
        try:
            self._jobs.put_nowait(job)
        except queue.Full:
            logger.info("a sound request was dropped: the queue is full")

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                job()
            except Exception:
                logger.warning("a sound request failed", exc_info=True)


class SoundService:
    """Plays the unit's sounds by name and keeps its sound policy current.

    ``call`` is the unit client's tool call (name, arguments); it raises when the unit is not
    connected. ``say`` speaks one short line and returns False when it cannot right now. ``night``
    is the host's verdict (quiet hours or the sensor night). ``quiet_minutes`` returns the
    household quiet hours as (from, to) minutes of the day, (-1, -1) for none. ``battery_low`` is
    the light service's confirmed low-battery fact. ``run_async`` runs a job off the caller's thread
    (a worker thread by default; tests pass an inline runner). ``clock`` and ``sleep`` are injected.
    """

    def __init__(
        self,
        call: Callable[[str, dict[str, object]], object],
        *,
        say: Callable[[str], bool] | None = None,
        night: Callable[[], bool] = lambda: False,
        quiet_minutes: Callable[[], tuple[int, int]] = lambda: (-1, -1),
        battery_low: Callable[[], bool] = lambda: False,
        run_async: Callable[[Callable[[], None]], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._call = call
        self._say = say
        self._night = night
        self._quiet_minutes = quiet_minutes
        self.battery_low = battery_low
        self._run_async = run_async or _Worker().submit
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self.enabled = True
        self.night_ok = False
        self.muted = False
        self.quiet = False
        self._firmware_ok = False  # the unit reports firmware that no longer needs the forced mute
        self._pushed: dict[str, object] | None = None
        self._pushed_at = float("-inf")
        self._push_failed_at = float("-inf")
        self._low_seen = False
        self._pending_line: float | None = None  # when to give up saying the low battery line
        self._camera_up = False
        self._last_shutter = float("-inf")
        self._info_at = float("-inf")
        self._info_last: dict[str, int] | None = None
        self._chimed: dict[str, list[float]] = {}  # when each cue last sounded (the last 24 hours)
        self.dance_active: Callable[[], bool] = lambda: False  # wired to the music session's state
        self._dance_was_active = False
        self._dance_quiet_until = float("-inf")  # the unit's event sounds stay off after it
        self.refusals: dict[str, int] = {}

    # ---- settings ----

    def apply_settings(self, values: Mapping[str, Any]) -> None:
        for key, attr in (
            (SOUNDS_ENABLED_KEY, "enabled"),
            (SOUNDS_NIGHT_KEY, "night_ok"),
            (MUTED_KEY, "muted"),
            (QUIET_KEY, "quiet"),
        ):
            value = values.get(key)
            if isinstance(value, bool):
                setattr(self, attr, value)
        self._run_async(self.push_policy)

    def _dance_silenced(self) -> bool:
        """A music session is running (``dance_active``) or ended less than 30 s ago: the unit's
        event sounds are off (owner 2026-11-14: "make those beeps go away"). Read from the
        session's own state every time the policy is built (about once a second), so a session
        that ends in any way restores the sounds by itself."""
        try:
            active = bool(self.dance_active())
        except Exception:
            active = False
        now = self._clock()
        with self._lock:
            if self._dance_was_active and not active:
                self._dance_quiet_until = now + DANCE_QUIET_AFTER_S
            self._dance_was_active = active
            return active or now < self._dance_quiet_until

    def policy(self) -> dict[str, object]:
        """What the unit is told: its own gate applies it, on its own clock, with the host away."""
        start, end = self._quiet_minutes()
        silenced = self._silenced()
        return {
            "enabled": self.enabled and not self._dance_silenced() and not silenced,
            "night_ok": self.night_ok,
            "muted": self.muted or self.quiet or silenced,  # full quiet is a mute for sounds
            "dark": bool(self._night()),
            "quiet_from": start,
            "quiet_to": end,
        }

    def _silenced(self) -> bool:
        """The forced mute: on until the unit reports firmware that fixes the beeping."""
        return bool(SILENCE_UNIT_SOUNDS) and not self._firmware_ok

    def on_firmware_version(self, version: object) -> None:
        """The unit said which firmware it runs (its `fw` event, about once a minute)."""
        parsed = _parse_version(version)
        ok = parsed is not None and parsed >= FIRMWARE_RESTORES_SOUNDS_FROM
        with self._lock:
            if ok == self._firmware_ok:
                return
            self._firmware_ok = ok
        log_activity(
            "sound policy follows the firmware",
            f"version={version} forced_mute={'off' if ok else 'on'}",
        )
        self._run_async(lambda: self.push_policy(force=True))

    def push_policy(self, *, force: bool = False) -> bool:
        """Tell the unit the policy when it changed (or every few minutes). True when it took it."""
        policy = self.policy()
        now = self._clock()
        with self._lock:
            every = SILENCED_POLICY_EVERY_S if self._silenced() else POLICY_EVERY_S
            if not force and policy == self._pushed and now - self._pushed_at < every:
                return True
            if not force and now - self._push_failed_at < PUSH_RETRY_S:
                return False
        try:
            result = _parse(self._call("self.audio.set_sound_policy", dict(policy)))
        except Exception:
            logger.debug("the unit's sound policy could not be set", exc_info=True)
            with self._lock:
                self._push_failed_at = now
            return False
        if result.get("ok") is not True:
            return False
        with self._lock:
            self._pushed, self._pushed_at = policy, now
        log_activity(
            "sound policy pushed",
            f"enabled={policy.get('enabled')} muted={policy.get('muted')} forced={force}",
        )
        return True

    def on_connect(self) -> None:
        """The unit connected (or reconnected): its policy is repeated; it may have rebooted."""
        with self._lock:
            self._pushed = None
            self._push_failed_at = float("-inf")
        self._run_async(lambda: self.push_policy(force=True))

    # ---- playing ----

    def refusal(self, name: str, *, urgent: bool = False, test: bool = False) -> str | None:
        """The word for why the host will not ask now (the unit judges again), or None."""
        if name not in EARCONS:
            return "unknown_sound"
        if self.muted or self.quiet:
            return "muted"
        if test:
            return None
        if not self.enabled and name not in SAFETY and not (name == "needs_you" and urgent):
            return "disabled"
        if self._night() and not self.night_ok and name not in NIGHT_OK:
            if not (name == "needs_you" and urgent):
                return "night"
        return None

    def _chime_gate(self, name: str) -> str | None:
        """The one chime gate: the cue is on the allowed list, has not sounded within its minimum
        gap and is under its daily cap. Records the chime when it passes. The sound test bypasses
        it."""
        if name not in CHIME_ALLOWED:
            return "not_allowed"
        now = self._clock()
        with self._lock:
            times = [t for t in self._chimed.get(name, []) if now - t < DAY_S]
            if times and now - times[-1] < CHIME_GAP_BY_CUE.get(name, CHIME_GAP_S):
                self._chimed[name] = times
                return "rate_limited"
            if len(times) >= CHIME_DAILY_CAP_BY_CUE.get(name, CHIME_DAILY_CAP):
                self._chimed[name] = times
                return "daily_cap"
            times.append(now)
            self._chimed[name] = times
        return None

    def play(self, name: str, *, urgent: bool = False, test: bool = False) -> PlayResult:
        """Ask the unit to play one sound now (blocks on the device; use ``play_later`` from an
        event thread)."""
        why = self.refusal(name, urgent=urgent, test=test)
        if why is None and not test:
            why = self._chime_gate(name)
        if why is not None:
            with self._lock:
                self.refusals[why] = self.refusals.get(why, 0) + 1
            return PlayResult(False, why)
        log_activity("sound requested", f"name={name} urgent={urgent} test={test}")
        try:
            result = _parse(
                self._call("self.audio.play_sound", {"name": name, "urgent": urgent, "test": test})
            )
        except Exception as exc:
            text = str(exc).lower()
            unsupported = "unknown tool" in text or "not supported" in text or "unsupported" in text
            return PlayResult(False, "unsupported" if unsupported else "unreachable")
        if result.get("ok") is True:
            return PlayResult(True)
        reason = result.get("error")
        return PlayResult(False, reason if isinstance(reason, str) and reason else "unreachable")

    def play_later(self, name: str, *, urgent: bool = False) -> None:
        self._run_async(lambda: self._play_logged(name, urgent))

    def _play_logged(self, name: str, urgent: bool) -> None:
        result = self.play(name, urgent=urgent)
        if not result.ok and result.reason not in (
            "muted",
            "night",
            "disabled",
            "not_allowed",
            "rate_limited",
            "daily_cap",
        ):
            logger.info("sound %s was not played: %s", name, result.reason)

    # ---- the host's events ----

    def on_camera_cue(self, active: bool) -> None:
        """The camera cue went up or down: one shutter click per picture session, at night too."""
        if not active:
            self._camera_up = False
            return
        now = self._clock()
        if self._camera_up or now - self._last_shutter < SHUTTER_GAP_S:
            self._camera_up = True
            return
        self._camera_up = True
        self._last_shutter = now
        self.play_later("shutter")

    def on_error_line(self) -> None:
        """An apology is about to be spoken: the error earcon comes first (at night it is the only
        sound, the apology itself being skipped by the quiet rules elsewhere)."""
        self.play_later("exclamation")

    def tick(self) -> None:
        """About once a second: the low battery sound and line, and the policy when it changed."""
        low = bool(self.battery_low())
        if low and not self._low_seen:
            self._low_seen = True
            self._pending_line = self._clock() + SPEAK_FOR_S
            self.play_later("low_battery")
        elif not low:
            self._low_seen = False
            self._pending_line = None
        if self._pending_line is not None:
            self._speak_low_battery()
        self._run_async(self.push_policy)
        now = self._clock()
        if now - self._info_at >= INFO_POLL_S:
            self._info_at = now
            self._run_async(self._poll_unit_counters)

    def _poll_unit_counters(self) -> None:
        """About once a minute: how many sounds the unit itself played since the last look, so a
        beep heard at a time can be matched to this log without a firmware flash. (The unit counts
        the sounds of its own list; the stock tones of the voice engine are not in it.)"""
        try:
            info = _parse(self._call("self.audio.sound_info", {}))
        except Exception:
            return
        keys = ("played", "refused", "clips_played", "clips_missing")
        now_counts = {k: int(info[k]) for k in keys if isinstance(info.get(k), int)}
        with self._lock:
            last, self._info_last = self._info_last, now_counts
        if last is None:
            log_activity("unit sound counters", " ".join(f"{k}={v}" for k, v in now_counts.items()))
            return
        delta = " ".join(f"{k}=+{now_counts[k] - last.get(k, 0)}" for k in now_counts)
        log_activity("unit sound counters since the last look", delta)

    def _speak_low_battery(self) -> None:
        until = self._pending_line
        if until is None or self._say is None:
            return
        if self._clock() > until:
            self._pending_line = None
            return
        if self._night() or self.muted or self.quiet or not self.enabled:
            self._pending_line = None  # at night, muted or off: the earcon only
            return
        try:
            said = self._say(LOW_BATTERY_LINE)
        except Exception:
            logger.warning("the low battery line could not be spoken", exc_info=True)
            said = False
        if said:
            self._pending_line = None

    # ---- the self-test ----

    def self_test(self) -> dict[str, object]:
        """Play every sound in turn (skips "off" and the night rule, never the mute); blocks for
        about ten seconds. Answers which played and which did not, with the reason."""
        played: list[str] = []
        failed: list[dict[str, str]] = []
        for name in EARCONS:
            result = self.play(name, test=True)
            if result.ok:
                played.append(name)
                self._sleep(SECONDS[name] + 0.4)
            else:
                failed.append({"sound": name, "reason": result.reason})
                if result.reason in ("muted", "unreachable", "unsupported"):
                    for rest in EARCONS[EARCONS.index(name) + 1 :]:
                        failed.append({"sound": rest, "reason": result.reason})
                    break
        return {"played": played, "failed": failed}

    def handlers(self) -> dict[str, Callable[[dict], dict]]:
        """The hub's ``sound_test`` command: starts the test and answers at once (the test takes
        about ten seconds and the command channel must not wait that long)."""

        def sound_test(_payload: dict) -> dict:
            reason = self.refusal("popup", test=True)
            if reason is not None:
                return {"sound_test": "refused", "why": reason}
            threading.Thread(
                target=self._run_test, name="stackchan-sound-test", daemon=True
            ).start()
            return {"sound_test": "started", "sounds": list(EARCONS)}

        return {"sound_test": sound_test}

    def _run_test(self) -> None:
        try:
            outcome = self.self_test()
        except Exception:
            logger.warning("the sound self-test failed", exc_info=True)
            return
        logger.info(
            "sound self-test: played %s; not played %s", outcome["played"], outcome["failed"]
        )


def _parse_version(version: object) -> tuple[int, int, int] | None:
    """ "0.2.102" -> (0, 2, 102); None for anything else ("unknown", a build suffix is ignored)."""
    if not isinstance(version, str):
        return None
    parts = version.strip().lstrip("v").split("-", 1)[0].split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return int(parts[0]), int(parts[1]), int(parts[2])
