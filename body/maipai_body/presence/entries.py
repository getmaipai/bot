"""Presence entries (age band only) from the vision watch and the hub's roster.

Only the nearest face carries a verdict, so it takes its person's band; every
other face is `unknown`. A face with no recognised person, or a person with no
known band, is `unknown` too: nothing here ever raises a band to adult. A watch
that is off reports nothing at all (None), which every consumer treats as the
safe direction.
"""

from __future__ import annotations

from collections.abc import Callable

from maipai_body.presence.carry_reaction import PresenceEntry
from maipai_body.vision.watch import WatchSnapshot


def presence_entries_from(
    snapshot: WatchSnapshot, band_of: Callable[[str], str | None]
) -> list[PresenceEntry] | None:
    if snapshot.level == "off":
        return None
    if snapshot.present <= 0:
        return []
    kind = "unknown"
    verdict = snapshot.verdict
    if verdict is not None and verdict.person_id is not None:
        band = band_of(verdict.person_id)
        if band in ("adult", "teen", "child"):
            kind = band
    return [PresenceEntry(kind)] + [PresenceEntry("unknown")] * (snapshot.present - 1)
