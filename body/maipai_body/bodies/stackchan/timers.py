"""On-unit timers and alarms, the host side (firmware patches 090 to 094).

The unit keeps the schedule in its own flash and rings it itself, so a timer works with the hub
down and survives a reboot; this module only sets, lists and cancels them through the unit's
``self.timer.*`` tools, keeps a count of what is active, and says the spoken line when the host is
up ("Your timer is done."). The ring, the face, the tone and the ending (a touch, the stop word)
belong to the firmware: this module never draws or plays anything.

Rules (the owner decided on-device timers on 2026-11-13):

* at most 8 active and a timer of at most 24 hours, the same caps as the firmware, checked here
  first so the person hears a plain reason;
* ``robot.timers.enabled`` (default on) turns off *setting* new ones; what is already on the unit
  still rings;
* a timer a person asked for rings at night too (the ring and the tone are the firmware's), but the
  spoken line is skipped in quiet hours and when muted, and a muted unit is told to ring without
  sound (``silent``).
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from maipai_body.settings_keys import TIMERS_ENABLED_KEY

logger = logging.getLogger("maipai_body.bodies.stackchan.timers")

MAX_ACTIVE = 8
MAX_TIMER_SECONDS = 86400
LABEL_MAX = 24
SPEAK_FOR_S = 30.0  # keep trying to say the line this long after it rang
_LABEL_OK = re.compile(r"[^A-Za-z0-9 .,'\-]")

# The firmware's error words, in the words a person would use.
_PLAIN = {
    "full": "I already have 8 timers and alarms going. Cancel one, then ask again.",
    "too_long": "A timer can be at most 24 hours. Ask for a shorter one, or set an alarm.",
    "no_clock": "My clock is not set yet, so I cannot set an alarm. Try again in a minute.",
    "not_found": "I could not find that timer. Ask me to list them, then name one.",
    "not_ringing": "Nothing is ringing right now.",
    "bad_argument": "I could not read that time. Say it again, for example 10 minutes or 7:30.",
}


class TimerError(ValueError):
    """Carries a message that says what went wrong and what to do about it."""


def clean_label(label: object) -> str:
    """A few plain words for the card and the spoken line: letters, digits, space and . , ' -."""
    if not isinstance(label, str):
        return ""
    return _LABEL_OK.sub("", " ".join(label.split()))[:LABEL_MAX].strip()


def done_line(kind: str, label: str) -> str:
    """What the robot says when one rings."""
    if kind == "alarm":
        return f"Your {label} alarm is going off." if label else "Your alarm is going off."
    return f"Your {label} timer is done." if label else "Your timer is done."


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


@dataclass
class _Pending:
    text: str
    until: float


class TimerService:
    """Sets and lists the unit's timers; says the line when one rings.

    ``call`` is the unit client's tool call (name, arguments) and may raise ``BodyLost`` when the
    unit is not connected. ``say`` speaks one short line and returns False when it cannot right now
    (a turn is on, no unit). ``clock`` is seconds on any steady scale, injected so tests are fast.
    """

    def __init__(
        self,
        call: Callable[[str, dict[str, object]], object],
        *,
        say: Callable[[str], bool] | None = None,
        muted: Callable[[], bool] = lambda: False,
        night: Callable[[], bool] = lambda: False,
        clock: Callable[[], float],
    ) -> None:
        self._call = call
        self._say = say
        self._muted = muted
        self._night = night
        self._clock = clock
        self._lock = threading.Lock()
        self.enabled = True
        self._active: dict[int, dict[str, Any]] | None = None  # None: not known yet
        self._pending: dict[int, _Pending] = {}

    # ---- settings ----

    def apply_settings(self, values: Mapping[str, Any]) -> None:
        value = values.get(TIMERS_ENABLED_KEY)
        if isinstance(value, bool):
            self.enabled = value

    # ---- the unit's tools ----

    def _tool(self, name: str, arguments: dict[str, object]) -> dict[str, Any]:
        reply = _parse(self._call(name, arguments))
        if reply.get("ok") is False:
            word = reply.get("error")
            raise TimerError(
                _PLAIN.get(word, _PLAIN["bad_argument"])
                if isinstance(word, str)
                else _PLAIN["bad_argument"]
            )
        return reply

    def _refuse_if_off(self) -> None:
        if not self.enabled:
            raise TimerError(
                "Timers are turned off for this robot. "
                "Turn on Timers in this robot's settings, then ask again."
            )

    def _room(self) -> None:
        count = self.active_count()
        if count is not None and count >= MAX_ACTIVE:
            raise TimerError(_PLAIN["full"])

    def set_timer(self, seconds: object, label: object = "") -> dict[str, Any]:
        self._refuse_if_off()
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 1:
            raise TimerError(_PLAIN["bad_argument"])
        if seconds > MAX_TIMER_SECONDS:
            raise TimerError(_PLAIN["too_long"])
        self._room()
        reply = self._tool(
            "self.timer.set",
            {"seconds": int(round(seconds)), "label": clean_label(label), "silent": self._muted()},
        )
        return self._remember(reply, "timer", int(round(seconds)), label)

    def set_alarm(self, hour: object, minute: object, label: object = "") -> dict[str, Any]:
        self._refuse_if_off()
        for value, high in ((hour, 23), (minute, 59)):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= high:
                raise TimerError(_PLAIN["bad_argument"])
        self._room()
        reply = self._tool(
            "self.timer.alarm",
            {"hour": hour, "minute": minute, "label": clean_label(label), "silent": self._muted()},
        )
        return self._remember(reply, "alarm", None, label)

    def _remember(self, reply: dict[str, Any], kind: str, seconds: int | None, label: object):
        timer_id = reply.get("id")
        if isinstance(timer_id, int) and not isinstance(timer_id, bool):
            with self._lock:
                if self._active is None:
                    self._active = {}
                self._active[timer_id] = {"kind": kind, "label": clean_label(label)}
        return {"ok": True, "id": timer_id, "kind": kind, "seconds": seconds}

    def list_timers(self) -> dict[str, Any]:
        reply = self._tool("self.timer.list", {})
        rows = reply.get("timers")
        timers = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        with self._lock:
            self._active = {
                r["id"]: {"kind": r.get("kind"), "label": r.get("label", "")}
                for r in timers
                if isinstance(r.get("id"), int)
            }
        return {"ok": True, "timers": timers, "clock": reply.get("clock") is True}

    def cancel(self, timer_id: int | None = None) -> dict[str, Any]:
        """Cancel one by id, or every one when ``timer_id`` is None."""
        self._tool("self.timer.cancel", {"id": 0 if timer_id is None else int(timer_id)})
        with self._lock:
            if self._active is not None:
                if timer_id is None:
                    self._active.clear()
                else:
                    self._active.pop(int(timer_id), None)
        return {"ok": True}

    def stop(self) -> dict[str, Any]:
        self._tool("self.timer.stop", {})
        return {"ok": True}

    def snooze(self, seconds: object = 300) -> dict[str, Any]:
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not 1 <= seconds <= 3600
        ):
            raise TimerError("A snooze can be 1 second to 1 hour. Ask for a time in that range.")
        reply = self._tool("self.timer.snooze", {"seconds": int(seconds)})
        return self._remember(reply, "timer", int(seconds), "")

    # ---- what is active (the check-in fact) ----

    def active_count(self) -> int | None:
        with self._lock:
            return None if self._active is None else len(self._active)

    def forget(self) -> None:
        """The unit reconnected or restarted: the count is unknown until the next list."""
        with self._lock:
            self._active = None
            self._pending.clear()

    # ---- the unit's events ----

    def on_event(self, kind: str, extra: Mapping[str, Any] | None) -> None:
        extra = extra or {}
        timer_id = extra.get("id")
        if not isinstance(timer_id, int) or isinstance(timer_id, bool):
            timer_id = None
        if kind == "timer_fired":
            label = clean_label(extra.get("label"))
            what = "alarm" if extra.get("what") == "alarm" else "timer"
            with self._lock:
                if timer_id is not None and self._active is not None:
                    self._active.pop(timer_id, None)
                if timer_id is not None and not self._muted() and not self._night():
                    self._pending[timer_id] = _Pending(
                        done_line(what, label), self._clock() + SPEAK_FOR_S
                    )
        elif kind == "timer_ended":
            with self._lock:
                if timer_id is not None:
                    self._pending.pop(timer_id, None)
                else:
                    self._pending.clear()
        elif kind == "timer_missed":
            logger.info(
                "unit timers: %s came due while it was off and were dropped", extra.get("dropped")
            )

    def tick(self) -> None:
        """Say a pending line when the robot is free; call about once a second."""
        if self._say is None:
            return
        now = self._clock()
        with self._lock:
            ready = [(i, p) for i, p in self._pending.items() if p.until > now]
            for timer_id in [i for i, p in self._pending.items() if p.until <= now]:
                del self._pending[timer_id]
        for timer_id, pending in ready[:1]:  # one line at a time
            try:
                said = self._say(pending.text)
            except Exception:
                logger.warning("timer line could not be spoken", exc_info=True)
                said = False
            if said:
                with self._lock:
                    self._pending.pop(timer_id, None)

    # ---- hub commands ----

    def handlers(self) -> dict[str, Callable[[dict], dict]]:
        """The hub's device commands for timers: each answers {ok, ...} or {ok: False, error}."""

        def guarded(fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
            def run(payload: dict) -> dict:
                try:
                    return fn(payload)
                except TimerError as exc:
                    return {"ok": False, "error": str(exc)}
                except Exception as exc:  # the unit is away or answered oddly
                    logger.warning("timer command failed", exc_info=True)
                    return {
                        "ok": False,
                        "error": "I could not reach my body to do that. "
                        "Check that it is on, then ask again.",
                        "detail": type(exc).__name__,
                    }

            return run

        return {
            "timer_set": guarded(lambda p: self.set_timer(p.get("seconds"), p.get("label", ""))),
            "alarm_set": guarded(
                lambda p: self.set_alarm(p.get("hour"), p.get("minute"), p.get("label", ""))
            ),
            "timer_list": guarded(lambda _p: self.list_timers()),
            "timer_cancel": guarded(
                lambda p: self.cancel(p["id"] if isinstance(p.get("id"), int) else None)
            ),
            "timer_stop": guarded(lambda _p: self.stop()),
            "timer_snooze": guarded(lambda p: self.snooze(p.get("seconds", 300))),
        }
