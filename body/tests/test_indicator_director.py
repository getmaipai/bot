"""EYES-02: the director turns the funnel's shown state plus the capture
facts into looks on the indicator. It reads nothing else."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from maipai_body.bodies.reachy_mini.fake import FakeEyes
from maipai_body.hal.seam import Palette
from maipai_body.indicator import looks
from maipai_body.indicator.director import EyesDirector
from maipai_body.indicator.live import CaptureFacts
from maipai_body.indicator.settings import IndicatorSettings
from maipai_body.presence.carry_reaction import PresenceEntry
from maipai_body.presence.funnel import FunnelState, FunnelView

PACKAGE = Path(__file__).resolve().parent.parent / "maipai_body"
DAY = 12 * 60
NIGHT = 23 * 60


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _director(*, settings=None, presence=None, minute=DAY, connected=True):
    clock = Clock()
    eyes = FakeEyes(connected=connected, clock=clock)
    state = {"settings": settings or IndicatorSettings(), "minute": minute, "presence": presence}
    director = EyesDirector(
        eyes,
        settings=lambda: state["settings"],
        presence=lambda: state["presence"],
        clock=clock,
        local_minutes=lambda: state["minute"],
        auto_timers=False,
    )
    return director, eyes, clock, state


def _colour(eyes: FakeEyes):
    return eyes.current_look.colour if eyes.current_look else None


def test_the_funnel_view_drives_the_table_row():
    director, eyes, _, _ = _director()
    director.on_view(FunnelView(shown=FunnelState.LISTENING))
    assert _colour(eyes) is looks.LOOKS[looks.LookKey.LISTENING][0]
    director.on_view(FunnelView(shown=FunnelState.THINKING))
    assert _colour(eyes) is looks.LOOKS[looks.LookKey.THINKING][0]
    director.on_view(FunnelView(shown=FunnelState.IDLE))
    assert _colour(eyes) is looks.LOOKS[looks.LookKey.IDLE][0]


def test_an_unchanged_look_is_not_resent():
    director, eyes, _, _ = _director()
    director.on_view(FunnelView(shown=FunnelState.LISTENING))
    director.on_view(FunnelView(shown=FunnelState.LISTENING))
    assert len(eyes.commands) == 1


def test_live_capture_outranks_everything_and_is_green():
    director, eyes, _, _ = _director()
    director.on_view(FunnelView(shown=FunnelState.SPEAKING, muted=True, held=True, alarm=True))
    director.on_capture(CaptureFacts(mic_live=True, camera_tracking=True, camera_read_at=None))
    assert _colour(eyes) is Palette.GREEN
    assert eyes.current_look.brightness >= looks.LIVE_FLOOR


def test_robot_indicator_enabled_false_never_turns_off_the_live_cue():
    director, eyes, clock, _ = _director(settings=IndicatorSettings(enabled=False))
    director.on_view(FunnelView(shown=FunnelState.LISTENING))
    assert eyes.current_look is None
    director.on_capture(CaptureFacts(mic_live=True, camera_tracking=False, camera_read_at=None))
    assert _colour(eyes) is Palette.GREEN
    clock.now += looks.CUE_HOLD_S
    director.on_capture(CaptureFacts(mic_live=False, camera_tracking=True, camera_read_at=None))
    assert _colour(eyes) is Palette.CYAN


def test_a_short_cue_is_held_for_the_cue_floor_time():
    director, eyes, clock, _ = _director()
    director.on_capture(CaptureFacts(mic_live=True, camera_tracking=False, camera_read_at=None))
    clock.now += 0.1
    director.on_capture(CaptureFacts(mic_live=False, camera_tracking=False, camera_read_at=None))
    assert _colour(eyes) is Palette.GREEN, "ended after 0.1 s but the floor holds it"
    clock.now += looks.CUE_HOLD_S
    director.tick()
    assert _colour(eyes) is not Palette.GREEN


def test_a_camera_frame_read_shows_the_camera_cue_for_the_hold():
    director, eyes, clock, _ = _director()
    director.on_capture(
        CaptureFacts(mic_live=False, camera_tracking=False, camera_read_at=clock.now)
    )
    assert _colour(eyes) is Palette.CYAN
    clock.now += looks.CUE_HOLD_S + 0.01
    director.tick()
    assert _colour(eyes) is not Palette.CYAN


def test_the_alarm_blinks_amber_no_faster_than_the_alarm_period():
    director, eyes, clock, _ = _director()
    director.on_view(FunnelView(shown=FunnelState.IDLE, alarm=True))
    for _ in range(100):
        clock.now += 0.1
        director.tick()
    on_level = looks.resolve(
        looks.LookRequest(
            funnel=FunnelState.IDLE,
            minute=DAY,
            settings=IndicatorSettings(),
            presence=None,
            alarm=True,
            alarm_on=True,
        )
    ).brightness
    bright = [
        c.t_s
        for c in eyes.commands
        if c.kind == "set_look" and c.look.colour is Palette.AMBER and c.look.brightness == on_level
    ]
    assert len(bright) >= 8
    gaps = [b - a for a, b in zip(bright, bright[1:], strict=False)]
    assert min(gaps) >= 1.0 - 1e-6, "the order: an alarm period of at least 1 s"


def test_the_alarm_stops_when_it_clears():
    director, eyes, clock, _ = _director()
    director.on_view(FunnelView(shown=FunnelState.IDLE, alarm=True))
    director.on_view(FunnelView(shown=FunnelState.IDLE, alarm=False))
    assert _colour(eyes) is looks.LOOKS[looks.LookKey.IDLE][0]
    sent = len(eyes.commands)
    clock.now += 5.0
    director.tick()
    assert len(eyes.commands) == sent


def test_night_with_a_child_is_dimmer_than_night_with_an_adult():
    director, eyes, _, state = _director(minute=NIGHT, presence=[PresenceEntry("adult")])
    director.on_view(FunnelView(shown=FunnelState.LISTENING))
    adult = eyes.current_look.brightness
    state["presence"] = [PresenceEntry("adult"), PresenceEntry("child")]
    director.refresh()
    assert eyes.current_look.brightness < adult


def test_the_quiet_night_idle_look_follows_sleep_eyes():
    director, eyes, _, _ = _director(minute=NIGHT, settings=IndicatorSettings(sleep_eyes="off"))
    director.on_view(FunnelView(shown=FunnelState.IDLE))
    assert eyes.current_look is None


def test_an_absent_device_never_raises():
    director, eyes, clock, _ = _director(connected=False)
    director.on_view(FunnelView(shown=FunnelState.SPEAKING, alarm=True))
    director.on_capture(CaptureFacts(mic_live=True, camera_tracking=False, camera_read_at=None))
    clock.now += 2.0
    director.tick()
    director.close()
    assert eyes.commands == []


def test_a_failing_indicator_does_not_break_the_caller():
    class Broken(FakeEyes):
        def set_look(self, look):
            raise OSError("serial gone")

    director = EyesDirector(Broken(), auto_timers=False)
    director.on_view(FunnelView(shown=FunnelState.LISTENING))


def test_close_turns_the_eyes_off():
    director, eyes, _, _ = _director()
    director.on_view(FunnelView(shown=FunnelState.LISTENING))
    director.close()
    assert eyes.current_look is None
    assert eyes.commands[-1].kind == "off"


def test_the_director_only_ever_pulses_blink_or_ack():
    director, eyes, clock, _ = _director()
    director.on_view(FunnelView(shown=FunnelState.SPEAKING, alarm=True, held=True))
    clock.now += 3.0
    director.tick()
    assert {c.pulse for c in eyes.commands if c.kind == "pulse"} <= {"blink", "ack"}


FORBIDDEN_IN_INDICATOR = (
    "maipai_body.speech.turn_client",
    "maipai_body.speech.playback",
    "maipai_body.speech.tts_playback",
    "maipai_body.speech.stt_stream",
    "maipai_body.vision",
    "maipai_body.run_loop",
    "maipai_body.expression",
    "maipai_body.presence.observations",
)


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            found.add(module)
            found |= {f"{module}.{alias.name}" for alias in node.names}
    return found


def test_indicator_imports_neither_the_turn_client_playback_nor_face_tracking():
    for path in sorted((PACKAGE / "indicator").glob("*.py")):
        for name in _imports(path):
            assert not name.startswith(FORBIDDEN_IN_INDICATOR), (path.name, name)
            assert not name.endswith(".FaceTracker"), (path.name, name)


def test_expression_never_imports_the_live_capture_tap():
    for path in sorted((PACKAGE / "expression").glob("*.py")):
        for name in _imports(path):
            assert "indicator.live" not in name, (path.name, name)
            assert name != "maipai_body.indicator.LiveCaptureTap", (path.name, name)


@pytest.mark.parametrize("path", sorted((PACKAGE / "expression").glob("*.py")))
def test_expression_does_not_import_the_indicator_package_for_looks(path):
    assert not any(name.startswith("maipai_body.indicator") for name in _imports(path)), path.name
