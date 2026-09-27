"""A scripted cue source: a fixed sequence of cues for bench testing.

Stands in for the household runtime's own cue stream, which does not
exist yet (EXPR-03 waits on it, gated on the hub's WIRE-01 and this
repo's own RUNTIME-01 pin). One cue per cue-mapped primitive, in a
fixed, repeatable order (EXPR-01's own acceptance: "every primitive
renders from its cue in the deterministic test").

``breathe`` and ``track`` are not cue-mapped (dev.md section 5: breathe
fires on the idle policy, track on a fresh direction of arrival or face
track, neither of which a turn's cue stream carries), so they are
exercised directly against the renderer in their own tests, not through
this sequence.
"""

from __future__ import annotations

from collections.abc import Iterator

from .cue import Cue, Phase


def scripted_bench_sequence() -> Iterator[Cue]:
    """One cue per primitive, in a fixed, repeatable order."""
    yield Cue(phase=Phase.HEARD, cue_seq=0)
    yield Cue(
        phase=Phase.SIGNAL,
        cue_seq=1,
        has_target=True,
        target_direction_rad=-0.6,
        react_allowed=True,
    )
    yield Cue(phase=Phase.SIGNAL, cue_seq=2, primary_act="question")
    yield Cue(phase=Phase.SIGNAL, cue_seq=3, primary_act="inform", react_allowed=True)
    yield Cue(
        phase=Phase.SIGNAL, cue_seq=4, expressed_emotion="happiness", emotion_intensity="high"
    )
    yield Cue(phase=Phase.SIGNAL, cue_seq=5, expressed_emotion="sadness")
    yield Cue(phase=Phase.SPEAK, cue_seq=6)
    yield Cue(phase=Phase.DONE, cue_seq=7)
    yield Cue(phase=Phase.CANCEL, cue_seq=8)
