"""SLEEP-AUTO-01: dark and quiet means sleep, arrival wakes.

``SleepAutoPolicy`` decides when the body enters or leaves the ``sleep``
state. It sees only a mean luma number (``mean_luma`` reduces a frame to
one float and keeps nothing), the DoA speech flag, a face flag and a knock.
It never touches audio: the wake word stays live because nothing here
pauses the capture or the spotter.

Rules:

* dark (mean luma under ``DARK_LUMA``) and no speech, both for 10 minutes,
  enter sleep. Light alone or sound alone never does: either one resets the
  clock. With no luma reading (the camera is off at watch level ``off``),
  the dark rule cannot run at all.
* a face, speech or a knock wakes within one call.
* quiet hours enter sleep regardless of light and sound, and the
  ``robot.sleep.auto`` setting gates only the dark-and-quiet rule. After a
  wake inside quiet hours the body stays awake until 10 minutes pass with
  no face and no speech.

``DARK_LUMA`` and the 10 minutes are design defaults, UNMEASURED.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from datetime import time as dtime
from typing import Literal

from maipai_body.settings_keys import QUIET_FROM_KEY, QUIET_TO_KEY

DARK_LUMA = 25.0  # of 255; UNMEASURED
QUIET_FOR_S = 600.0

SleepEdge = Literal["sleep", "wake"]


def mean_luma(frame: object) -> float:
    """Reduce a frame (H x W or H x W x C array) to its mean value; nothing is kept."""
    import numpy as np

    return float(np.asarray(frame, dtype=np.float32).mean())


def luma_reader(
    camera: object, *, level: Callable[[], str] = lambda: "presence"
) -> Callable[[], float | None]:
    """A luma source over a camera with ``get_frame``. At watch level ``off`` the camera
    is never read; the frame is subsampled and nothing is kept."""

    def read() -> float | None:
        if level() == "off":
            return None
        frame = camera.get_frame()  # type: ignore[attr-defined]
        if frame is None:
            return None
        import numpy as np

        return mean_luma(np.asarray(frame)[::8, ::8])

    return read


def _parse_clock(value: object) -> dtime | None:
    if not isinstance(value, str):
        return None
    try:
        hour, minute = value.split(":")
        return dtime(int(hour), int(minute))
    except ValueError:
        return None


DEFAULT_QUIET_FROM = dtime(21, 0)  # the registry defaults of household.quiet_hours.*
DEFAULT_QUIET_TO = dtime(7, 0)


class QuietHours:
    """The household quiet-hours window, from the hub's settings frame.

    ``household.quiet_hours.from`` and ``.to`` are registry keys honoured by ``bot``
    (spec-v0.1.151). Until the hub sends them the registry defaults apply (21:00 to
    07:00), so a settings frame that only carries changes still gives the right window.
    A window that crosses midnight is handled; equal bounds mean never; a malformed
    value keeps the last good one."""

    def __init__(self, now: Callable[[], datetime] = datetime.now) -> None:
        self._now = now
        self._from: dtime = DEFAULT_QUIET_FROM
        self._to: dtime = DEFAULT_QUIET_TO

    def apply(self, values: Mapping[str, object]) -> None:
        start = _parse_clock(values.get(QUIET_FROM_KEY))
        end = _parse_clock(values.get(QUIET_TO_KEY))
        if start is not None:
            self._from = start
        if end is not None:
            self._to = end

    def active(self) -> bool:
        if self._from == self._to:
            return False
        now = self._now().time()
        if self._from < self._to:
            return self._from <= now < self._to
        return now >= self._from or now < self._to


@dataclass
class SleepAutoPolicy:
    auto_enabled: bool = True
    asleep: bool = False

    def __post_init__(self) -> None:
        self._dark_since: float | None = None
        self._last_sound: float | None = None
        self._last_activity: float | None = None
        self._was_quiet_hours = False

    def update(
        self,
        now: float,
        *,
        luma: float | None,
        speech: bool,
        face: bool,
        knock: bool = False,
        quiet_hours: bool = False,
    ) -> SleepEdge | None:
        """One presence tick. Returns the edge when the state changes."""
        if self._last_sound is None:
            self._last_sound = now
        if self._last_activity is None:
            self._last_activity = now
        if speech:
            self._last_sound = now
        if speech or face:
            self._last_activity = now

        if luma is not None and luma < DARK_LUMA:
            if self._dark_since is None:
                self._dark_since = now
        else:
            self._dark_since = None

        quiet_edge = quiet_hours and not self._was_quiet_hours
        self._was_quiet_hours = quiet_hours

        if self.asleep:
            if face or speech or knock:
                self.asleep = False
                return "wake"
            return None

        if quiet_hours and (quiet_edge or now - self._last_activity >= QUIET_FOR_S):
            if not (face or speech or knock):
                self.asleep = True
                return "sleep"
        if (
            self.auto_enabled
            and self._dark_since is not None
            and now - self._dark_since >= QUIET_FOR_S
            and now - self._last_sound >= QUIET_FOR_S
            and not face
        ):
            self.asleep = True
            return "sleep"
        return None
