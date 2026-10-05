"""MOVE-CARRY-01b: while held the body commands no motion; after put down it
settles and resumes. Driven by scripted IMU readings through the real
presence tick, with the real expression engine on the fake body."""

from __future__ import annotations

import threading

import pytest

from maipai_body.bodies.reachy_mini.fake import freefall_reading, rest_reading, tipped_reading
from maipai_body.expression.cue import Cue, Phase
from maipai_body.expression.primitives import MUTED_STATE, PRIMITIVE_NAMES
from maipai_body.expression.suppression import SuppressionContext, suppression_reason
from maipai_body.hal.seam import FaceTrackTarget
from maipai_body.presence import motion_state
from maipai_body.presence.motion_state import MotionState
from tests.test_motion_state import shaken
from tests.test_run_loop import _make_loop

MOTION_KINDS = {"goto", "set_target"}


def test_every_primitive_but_stop_is_suppressed_while_held():
    context = SuppressionContext(held=True)
    for primitive in (*PRIMITIVE_NAMES, MUTED_STATE):
        expected = None if primitive == "stop" else "held"
        assert suppression_reason(primitive, context) == expected


class Bench:
    """One loop, a hand-set IMU reading and a hand-set clock; one tick at a time."""

    def __init__(self, **loop_kwargs) -> None:
        self.loop, self.parts = _make_loop(**loop_kwargs)
        self.client = self.parts["client"]
        self.reading = rest_reading()
        self.now = 100.0
        self.client.read = lambda: self.reading
        self.loop._motion_clock = lambda: self.now
        self.stop = threading.Event()

    def tick(self, seconds: float, reading=None, *, shake: bool = False) -> None:
        for step in range(round(seconds / 0.1)):
            self.reading = shaken(step) if shake else (reading or rest_reading())
            self.loop._presence_tick(self.stop)
            self.now += 0.1

    def kinds(self) -> list[str]:
        return [command.kind for command in self.client.sent_commands]


def face() -> FaceTrackTarget:
    return FaceTrackTarget(detected=True, x=0.5, y=0.5)


def test_lifting_stops_tracking_and_holds_the_head_once():
    bench = Bench()
    bench.client.face_target = face()
    bench.tick(0.3)
    assert bench.loop.state.tracking
    bench.tick(1.0, shake=True)
    assert bench.loop.motion_state is MotionState.LIFTED
    assert not bench.loop.state.tracking
    assert not bench.client.tracking_enabled
    assert bench.kinds().count("hold") == 1
    bench.tick(3.0, shake=True)
    assert bench.kinds().count("hold") == 1


def test_nothing_is_commanded_while_held():
    bench = Bench()
    bench.client.face_target = face()
    bench.tick(1.0, shake=True)
    mark = len(bench.client.sent_commands)
    bench.loop._render(Cue(phase=Phase.SPEAK, cue_seq=1))
    bench.loop._render(Cue(phase=Phase.HEARD, cue_seq=2))
    assert bench.loop._render_ambient("breathe") is False
    assert bench.loop._render_ambient("settle") is False
    bench.tick(3.0, shake=True)  # a face stays in view the whole time
    assert [c for c in bench.client.sent_commands[mark:] if c.kind in MOTION_KINDS] == []
    assert not bench.client.tracking_enabled


def test_cancel_still_holds_the_pose_while_held():
    bench = Bench()
    bench.tick(1.0, shake=True)
    mark = len(bench.client.sent_commands)
    bench.loop._render(Cue(phase=Phase.CANCEL, cue_seq=3))
    assert [c.kind for c in bench.client.sent_commands[mark:]] == ["hold"]


def test_a_react_move_is_not_played_while_held():
    calls: list[str] = []
    bench = Bench(react_hook=lambda move, *_a, **_k: calls.append(move) or True)
    bench.tick(1.0, shake=True)
    bench.loop._play_react("wave", True)
    assert calls == []
    bench.tick(motion_state.PUT_DOWN_STILL_S + 0.5)
    bench.loop._play_react("wave", True)
    assert calls == ["wave"]


def test_put_down_settles_once_then_everything_resumes():
    bench = Bench()
    bench.client.face_target = face()
    bench.tick(4.0, shake=True)
    assert bench.loop.motion_state is MotionState.CARRIED
    bench.tick(motion_state.PUT_DOWN_STILL_S - 0.5)
    assert bench.kinds().count("goto") == 0  # still inside the stillness window
    assert not bench.client.tracking_enabled
    bench.tick(1.0)
    settles = [c for c in bench.client.sent_commands if c.kind == "goto"]
    assert len(settles) == 1
    assert settles[0].pose.pitch == 0.0 and settles[0].pose.yaw == 0.0
    assert bench.loop.motion_state is MotionState.RESTING
    assert bench.client.tracking_enabled  # the face is still there: tracking resumes
    assert bench.loop._render_ambient("breathe") is True


def test_a_bump_holds_nothing():
    bench = Bench()
    bench.client.face_target = face()
    bench.tick(0.3)
    bench.tick(0.2, shake=True)
    bench.tick(3.0)
    assert "hold" not in bench.kinds()
    assert bench.client.tracking_enabled


def test_tipped_and_freefall_outrank_the_hold_states_and_keep_it_latched():
    bench = Bench()
    bench.tick(4.0, shake=True)
    bench.tick(1.0, freefall_reading())
    assert bench.loop.motion_state is MotionState.FREEFALL
    bench.tick(1.0, tipped_reading(1.2))
    assert bench.loop.motion_state is MotionState.TIPPED
    assert bench.loop._render_ambient("breathe") is False  # still held
    assert not [c for c in bench.client.sent_commands if c.kind in MOTION_KINDS]


def test_the_freefall_line_is_still_said_once_per_fall(monkeypatch):
    bench = Bench()
    said: list[str] = []
    monkeypatch.setattr(bench.loop, "_say_clip", lambda clip: said.append(clip) or True)
    bench.tick(4.0, shake=True)
    bench.tick(1.0, freefall_reading())
    assert len(said) == 1


def test_gravity_compensation_stays_off_by_default_through_a_full_lift():
    bench = Bench()
    bench.tick(4.0, shake=True)
    bench.tick(motion_state.PUT_DOWN_STILL_S + 1.0)
    assert not {"gravity_on", "gravity_off", "disable"} & set(bench.kinds())


def _gravity_bench(*, teach_active: bool = False) -> Bench:
    bench = Bench()
    bench.loop._carry_gravity_compensation = True
    bench.loop._teach_active = lambda: teach_active
    return bench


def test_gravity_compensation_follows_the_hold_only_behind_the_profile_flag():
    bench = _gravity_bench()
    bench.tick(1.0, shake=True)
    assert bench.client.gravity_compensation
    bench.tick(motion_state.PUT_DOWN_STILL_S + 1.0)
    assert not bench.client.gravity_compensation


def test_gravity_compensation_is_never_toggled_while_teach_holds_it():
    bench = _gravity_bench(teach_active=True)
    bench.tick(1.0, shake=True)
    bench.tick(motion_state.PUT_DOWN_STILL_S + 1.0)
    assert not {"gravity_on", "gravity_off"} & set(bench.kinds())


def test_the_profile_flag_defaults_off():
    from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE

    assert REACHY_MINI_PROFILE.carry_gravity_compensation is False


@pytest.mark.parametrize("seconds", [0.0])
def test_no_imu_reading_never_holds(seconds):
    bench = Bench()
    bench.client.read = lambda: None
    bench.tick(5.0)
    assert bench.loop.motion_state is MotionState.RESTING
