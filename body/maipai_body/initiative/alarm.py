"""ALARM-PLAY-01: the safety alarm on the robot (deterministic, no model).

The hub's `alarm` command (`home/backend/src/lib/safetyAlarm.ts`) carries
`{alarm_id, area, kind, state}` with `state` one of `active`, `cleared` or
`false_alarm`. This module plays the alarm and obeys the next state:

* a chime and the area line (the generic line when the area line is not in the
  bundle), at the volume floor or above, through quiet hours, mute and
  initiative-off (none of those are read here);
* the alarm pose and the amber pulse, held while the alarm is active;
* a repeat on every `active` command (the hub repeats every
  `safety.alarm.repeat_seconds`) and a local backstop at one and a half times that
  interval, so a lost channel does not silence a live alarm;
* the child line as well when anyone present is a child or unknown;
* a spotted "stop" is one `alarm_action` acknowledgement carrying the speaker's
  evidence. It does not silence anything: only the hub's next state does.

It never synthesises speech and never runs a turn: it imports no speech
client, turn client or model. Clips come from the hub's bundle through the
injected player.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

logger = logging.getLogger("maipai_body.initiative.alarm")

VOLUME_FLOOR = 70  # safety.alarm.volume has a hard floor of 70
REPEAT_MIN_S = 10.0
REPEAT_MAX_S = 60.0
REPEAT_DEFAULT_S = 20.0
BACKSTOP_FACTOR = 1.5
# What a spotted word may acknowledge. "stop" is the keyword spotter's word;
# "i know" waits on the keyword model's phrase list (BACKLOG, open).
ACK_PHRASES = frozenset({"stop", "i know"})
ACK_ACTION = "acknowledge"
ACTIVE, CLEARED, FALSE_ALARM = "active", "cleared", "false_alarm"


class AlarmPlayer(Protocol):
    """Plays the chime and bundle clips. Never synthesises."""

    def chime(self) -> None: ...

    def clips(self, clip_ids: Sequence[str]) -> bool: ...

    def stop(self) -> None: ...


class Volume(Protocol):
    def get_level(self) -> int: ...

    def set_level(self, level: int) -> None: ...


class AlarmPresenter(Protocol):
    """The pose and the amber pulse. `True` holds both; `False` releases them."""

    def __call__(self, active: bool) -> None: ...


def chime_samples(sample_rate: int) -> npt.NDArray[np.float32]:
    """A fixed two-note chime: plain tones, so it needs no model or bundle."""
    parts = []
    for freq in (880.0, 660.0):
        t = np.arange(int(0.28 * sample_rate)) / sample_rate
        envelope = np.minimum(1.0, np.minimum(t / 0.01, (0.28 - t) / 0.06))
        parts.append((0.6 * envelope * np.sin(2 * np.pi * freq * t)).astype(np.float32))
    return np.concatenate(parts)


def clamp_repeat(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return REPEAT_DEFAULT_S
    return min(max(float(value), REPEAT_MIN_S), REPEAT_MAX_S)


class AlarmController:
    def __init__(
        self,
        *,
        player: AlarmPlayer,
        present: AlarmPresenter,
        resolve_clips: Callable[[str | None, str | None], list[str]],
        child_clips: Callable[[], list[str]],
        send_action: Callable[[dict], bool],
        audience: Callable[[], Sequence[dict]],
        is_child: Callable[[dict], bool],
        evidence: Callable[[], dict],
        volume: Volume | None = None,
        clock: Callable[[], float] = time.monotonic,
        repeat_seconds: float = REPEAT_DEFAULT_S,
        volume_setting: int = VOLUME_FLOOR,
    ) -> None:
        self._player = player
        self._present = present
        self._resolve = resolve_clips
        self._child = child_clips
        self._send = send_action
        self._audience = audience
        self._is_child = is_child
        self._evidence = evidence
        self._volume = volume
        self._clock = clock
        self._repeat_s = clamp_repeat(repeat_seconds)
        self._volume_setting = volume_setting
        self._lock = threading.RLock()
        self._alarm_id: str | None = None
        self._area: str | None = None
        self._kind: str | None = None
        self._last_play = 0.0
        self._acked: str | None = None
        self._saved_volume: int | None = None

    # -- state ----------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._alarm_id is not None

    @property
    def alarm_id(self) -> str | None:
        return self._alarm_id

    def alarm_volume(self) -> int:
        return min(100, max(VOLUME_FLOOR, int(self._volume_setting)))

    # -- settings_changed -------------------------------------------------

    def apply_settings(self, values: dict) -> None:
        if "safety.alarm.repeat_seconds" in values:
            self._repeat_s = clamp_repeat(values["safety.alarm.repeat_seconds"])
        volume = values.get("safety.alarm.volume")
        if isinstance(volume, (int, float)) and not isinstance(volume, bool):
            self._volume_setting = int(volume)  # the floor is applied when read

    # -- the hub's `alarm` command -----------------------------------------

    def handle_command(self, payload: dict) -> dict | None:
        alarm_id = payload.get("alarm_id")
        state = payload.get("state")
        if not isinstance(alarm_id, str) or not alarm_id:
            raise ValueError("alarm command needs an alarm_id")
        if state == ACTIVE:
            self._start_or_repeat(alarm_id, payload)
        elif state in (CLEARED, FALSE_ALARM):
            self._end(alarm_id)
        else:
            raise ValueError(f"alarm command has an unknown state {state!r}")
        return None

    def _start_or_repeat(self, alarm_id: str, payload: dict) -> None:
        with self._lock:
            new = self._alarm_id != alarm_id
            if new:
                self._alarm_id = alarm_id
                self._acked = None
                kind, area = payload.get("kind"), payload.get("area")
                self._kind = kind if isinstance(kind, str) else None
                self._area = area if isinstance(area, str) else None
                self._raise_volume()
                self._set_present(True)
            self._play()

    def _end(self, alarm_id: str) -> None:
        with self._lock:
            if self._alarm_id != alarm_id:
                return
            self._alarm_id = None
            self._acked = None
        try:
            self._player.stop()
        except Exception:
            logger.warning("stopping alarm playback failed", exc_info=True)
        self._restore_volume()
        self._set_present(False)

    def _set_present(self, active: bool) -> None:
        try:
            self._present(active)
        except Exception:
            logger.warning("alarm pose and look failed (the sound still plays)", exc_info=True)

    def _raise_volume(self) -> None:
        if self._volume is None:
            return
        try:
            self._saved_volume = self._volume.get_level()
            self._volume.set_level(self.alarm_volume())
        except Exception:
            logger.warning("could not raise the alarm volume", exc_info=True)

    def _restore_volume(self) -> None:
        if self._volume is None or self._saved_volume is None:
            return
        try:
            self._volume.set_level(self._saved_volume)
        except Exception:
            logger.warning("could not restore the volume after the alarm", exc_info=True)
        self._saved_volume = None

    def _play(self) -> None:
        self._last_play = self._clock()
        try:
            self._player.chime()
        except Exception:
            logger.warning("alarm chime failed", exc_info=True)
        ids = list(self._resolve(self._kind, self._area))
        try:
            if ids:
                self._player.clips(ids)
            if any(self._is_child(entry) for entry in self._audience()):
                child = list(self._child())
                if child:
                    self._player.clips(child)
        except Exception:
            logger.warning("alarm line failed", exc_info=True)

    def tick(self) -> None:
        """The local backstop: replay when the hub's repeat has not come."""
        with self._lock:
            if self._alarm_id is None:
                return
            if self._clock() - self._last_play < self._repeat_s * BACKSTOP_FACTOR:
                return
            self._play()

    # -- a spotted word ---------------------------------------------------

    def on_spoken(self, phrase: str) -> bool:
        """ "stop" or "I know" during an alarm: one acknowledgement per alarm, with
        the speaker's evidence. Returns whether one was sent. Nothing stops until
        the hub's state changes."""
        if phrase.strip().lower() not in ACK_PHRASES:
            return False
        with self._lock:
            alarm_id = self._alarm_id
            if alarm_id is None or self._acked == alarm_id:
                return False
            self._acked = alarm_id
        message = {
            "type": "alarm_action",
            "alarm_id": alarm_id,
            "action": ACK_ACTION,
            "speaker_evidence": self._evidence(),
        }
        try:
            sent = bool(self._send(message))
        except Exception:
            logger.warning("alarm acknowledgement failed to send", exc_info=True)
            sent = False
        if not sent:
            with self._lock:
                if self._acked == alarm_id:
                    self._acked = None  # the channel was down: the next "stop" may try again
        return sent
