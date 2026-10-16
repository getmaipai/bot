"""FOLLOWUP-01: the follow-up window without the wake word.

After a reply and the 450 ms tail, the stream reopens for a few seconds so
a person can answer without saying the wake word again. Whether it opens is
decided from the speaker's evidence, never from the utterance:

* `robot.follow_up.seconds` (device, default 8, 0 turns the window off);
* adults and teens get it by default, a person can switch it off with
  `person.robot.follow_up`;
* a child gets it only when a parent has turned that person's switch on;
* a claimed speaker ("it's me") never opens it;
* an unknown speaker (no person, or unknown level) is the child default,
  which is off, whoever else is present.

Where the band and the switch come from is a seam (`PeopleDirectory`): the
hub's roster feed fills it. Until a feed fills it, every speaker is the child
default and the window stays closed, which is the safe direction.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from maipai_body.speaker_evidence import AgeBand, SpeakerEvidence, effective_band

DEFAULT_SECONDS = 8.0
MAX_SECONDS = 20.0


@dataclass
class PeopleDirectory:
    """Age band and follow-up switch per person, as the hub last said."""

    _bands: dict[str, AgeBand] = field(default_factory=dict)
    _switches: dict[str, bool] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def update(
        self, person_id: str, *, band: AgeBand | None = None, follow_up: bool | None = None
    ) -> None:
        with self._lock:
            if band is not None:
                self._bands[person_id] = band
            if follow_up is not None:
                self._switches[person_id] = follow_up

    def forget(self, person_id: str) -> None:
        with self._lock:
            self._bands.pop(person_id, None)
            self._switches.pop(person_id, None)

    def band_of(self, person_id: str) -> AgeBand | None:
        with self._lock:
            return self._bands.get(person_id)

    def follow_up_switch(self, person_id: str) -> bool | None:
        with self._lock:
            return self._switches.get(person_id)


class FollowUpPolicy:
    def __init__(self, directory: PeopleDirectory, *, seconds: float = DEFAULT_SECONDS) -> None:
        self._directory = directory
        self._lock = threading.Lock()
        self._seconds = self._clamp(seconds)

    @staticmethod
    def _clamp(value: float) -> float:
        return min(max(float(value), 0.0), MAX_SECONDS)

    @property
    def seconds(self) -> float:
        with self._lock:
            return self._seconds

    def set_seconds(self, value: float) -> None:
        """The device's `robot.follow_up.seconds`, from the hub's settings_changed."""
        with self._lock:
            self._seconds = self._clamp(value)

    def window(self, evidence: SpeakerEvidence | None) -> float:
        """Seconds to reopen the stream for this speaker; 0 means do not."""
        seconds = self.seconds
        if seconds <= 0:
            return 0.0
        if evidence is not None and evidence["basis"] == "claimed":
            return 0.0  # a claim selects a person for personalization, never access
        band, _basis = effective_band(evidence, self._directory.band_of)
        person = evidence["person"] if evidence is not None else None
        switch = self._directory.follow_up_switch(person) if person is not None else None
        if band in ("adult", "teen"):
            return seconds if switch is not False else 0.0
        return seconds if switch is True else 0.0
