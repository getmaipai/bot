"""MOVE-CARRY-01c: the held look, the one short line, and the setting.

The look is the antenna pose; the line is a G4b clip, played at most once
per lift, never over a turn, and only when every presence entry is a known
adult. The holds of 01b are the floor and are not governed by the setting.
"""

from __future__ import annotations

import pytest

from maipai_body.link.hello import CARRY_REACTION_KEY, settings_declaration
from maipai_body.presence import motion_state
from maipai_body.presence.carry_reaction import (
    CARRY_LINES,
    CarryReaction,
    PresenceEntry,
    line_allowed,
)
from maipai_body.run_loop import FunnelState
from maipai_body.speech import offline_clips as oc
from tests.ladder_fakes import FakeSpeaker
from tests.test_link_ladder_run_loop import _rungs
from tests.test_motion_state_hold import Bench

ADULT = PresenceEntry(kind="adult")


class CarryBench(Bench):
    def __init__(self, reaction=CarryReaction.LOOK, entries=(ADULT,), speaker=None, **kw) -> None:
        self.speaker = speaker if speaker is not None else FakeSpeaker()
        offline, *_ = _rungs(speaker=self.speaker)
        super().__init__(offline=offline, **kw)
        self.reaction = reaction
        self.entries = entries
        self.loop._carry_reaction = lambda: self.reaction
        self.loop._presence_entries = lambda: self.entries

    def antenna_gotos(self):
        return [c for c in self.client.sent_commands if c.kind == "goto"]

    def lift_and_put_down(self) -> None:
        self.tick(3.0, shake=True)
        self.tick(motion_state.PUT_DOWN_STILL_S + 2.0)


def spoken(bench: CarryBench) -> list[str]:
    return [ids[0] for ids in bench.speaker.said]


# ---- who may hear the line ----------------------------------------------------------------


def test_the_line_needs_every_entry_to_be_a_known_adult():
    assert line_allowed([ADULT])
    assert line_allowed([ADULT, ADULT])
    for other in ("child", "teen", "unknown"):
        assert not line_allowed([ADULT, PresenceEntry(kind=other)])
        assert not line_allowed([PresenceEntry(kind=other)])
    assert not line_allowed([])
    assert not line_allowed(None)


def test_the_presence_kinds_are_closed():
    with pytest.raises(ValueError):
        PresenceEntry(kind="grown-up")


# ---- the look ------------------------------------------------------------------------------


def test_look_puts_the_antennas_soft_and_low_once_and_leaves_the_head_alone():
    bench = CarryBench()
    bench.tick(5.0, shake=True)
    gotos = bench.antenna_gotos()
    assert len(gotos) == 1
    look = gotos[0]
    assert look.pose is None and look.body_yaw is None
    assert look.antennas.left < 0 and look.antennas.right < 0
    assert spoken(bench) == []
    assert bench.kinds().count("hold") == 1


def test_off_leaves_the_holds_in_place_and_does_nothing_else():
    bench = CarryBench(reaction=CarryReaction.OFF)
    bench.client.face_target = bench.client.face_target.model_copy(update={"detected": True})
    bench.tick(5.0, shake=True)
    assert bench.antenna_gotos() == []
    assert spoken(bench) == []
    assert bench.kinds().count("hold") == 1  # the head still holds
    assert not bench.client.tracking_enabled
    assert bench.loop._render_ambient("breathe") is False  # still suppressed
    bench.tick(motion_state.PUT_DOWN_STILL_S + 1.0)
    assert len(bench.antenna_gotos()) == 1  # the settle after put down still runs


def test_a_muted_body_keeps_its_own_antenna_pose():
    bench = CarryBench()
    bench.loop._state.muted = True
    bench.tick(3.0, shake=True)
    assert bench.antenna_gotos() == []


# ---- the line ------------------------------------------------------------------------------


def test_look_alone_never_speaks():
    bench = CarryBench(reaction=CarryReaction.LOOK)
    bench.lift_and_put_down()
    assert spoken(bench) == []


def test_look_and_line_speaks_once_per_lift_from_the_closed_set():
    bench = CarryBench(reaction=CarryReaction.LOOK_AND_LINE)
    bench.tick(10.0, shake=True)  # a long carry
    assert len(spoken(bench)) == 1
    assert spoken(bench)[0] in CARRY_LINES


def test_the_variants_rotate_across_lifts():
    bench = CarryBench(reaction=CarryReaction.LOOK_AND_LINE)
    for _ in range(len(CARRY_LINES) + 1):
        bench.lift_and_put_down()
    said = spoken(bench)
    assert said[: len(CARRY_LINES)] == list(CARRY_LINES)
    assert said[len(CARRY_LINES)] == CARRY_LINES[0]


@pytest.mark.parametrize(
    "funnel", [FunnelState.LISTENING, FunnelState.THINKING, FunnelState.SPEAKING]
)
def test_the_line_is_never_said_over_a_turn(funnel):
    bench = CarryBench(reaction=CarryReaction.LOOK_AND_LINE)
    bench.loop._enter(funnel)
    bench.tick(5.0, shake=True)
    assert spoken(bench) == []
    assert len(bench.antenna_gotos()) == 1  # the look still shows


@pytest.mark.parametrize(
    "entries",
    [
        (ADULT, PresenceEntry(kind="child")),
        (ADULT, PresenceEntry(kind="teen")),
        (ADULT, PresenceEntry(kind="unknown")),
        (PresenceEntry(kind="child"),),
        (),
        None,
    ],
)
def test_the_line_stays_silent_unless_every_entry_is_a_known_adult(entries):
    bench = CarryBench(reaction=CarryReaction.LOOK_AND_LINE, entries=entries)
    bench.lift_and_put_down()
    assert spoken(bench) == []
    assert len(bench.antenna_gotos()) == 2  # the silent look, then the settle


def test_no_presence_source_at_all_is_the_silent_look():
    bench = CarryBench(reaction=CarryReaction.LOOK_AND_LINE)
    bench.loop._presence_entries = None
    bench.tick(5.0, shake=True)
    assert spoken(bench) == []


def test_an_unrendered_clip_is_silent_and_harmless():
    bench = CarryBench(reaction=CarryReaction.LOOK_AND_LINE, speaker=FakeSpeaker(available=set()))
    bench.tick(5.0, shake=True)
    assert spoken(bench) == []
    assert len(bench.antenna_gotos()) == 1


def test_the_default_setting_is_look():
    bench = Bench()
    assert bench.loop._carry_reaction() is CarryReaction.LOOK


# ---- the setting and the clips -------------------------------------------------------------


def test_the_setting_is_declared_for_hello_with_label_and_lives_in():
    declared = {s["key"]: s for s in settings_declaration()}
    setting = declared[CARRY_REACTION_KEY]
    assert CARRY_REACTION_KEY == "robot.motion.carry_reaction"
    assert setting["type"] == "select"
    assert setting["options"] == ["off", "look", "look_and_line"]
    assert setting["default"] == "look"
    assert setting["scope"] == "device"
    assert setting["label"] and setting["lives_in"]
    assert "—" not in setting["label"] + setting["lives_in"]


def test_the_line_variants_are_shipped_clips_written_for_the_youngest_listener():
    manifest = oc.load_manifest()
    for clip_id in CARRY_LINES:
        text = manifest.clip(clip_id).text
        assert "—" not in text and len(text.split()) <= 6
    assert len(CARRY_LINES) == 3
