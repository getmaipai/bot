"""EYES-02: the funnel's published facts reach the eyes, and a fast turn
replays through the real loop, tap and director with no flash.

The legacy trace is not in this clone; the replay is a scripted fast turn of
the same shape (a hello answered in milliseconds), run with the real 0.5 s gate.
"""

from __future__ import annotations

from maipai_body.bodies.reachy_mini.fake import FakeEyes, tipped_reading
from maipai_body.expression.cue import Cue, Phase
from maipai_body.hal.seam import Palette
from maipai_body.indicator.director import EyesDirector
from maipai_body.indicator.live import LiveCaptureTap
from maipai_body.presence.funnel import FunnelState, FunnelView
from maipai_body.run_loop import SETTLE_GATE_S
from maipai_body.speech.stt_stream import SttStreamResult
from maipai_body.speech.turn_client import TurnEvent
from maipai_body.speech.wake import WakeEvent
from tests.test_motion_state_hold import Bench
from tests.test_run_loop import _make_loop, _start, _stop, _wait_for

CUE_COLOURS = {Palette.GREEN, Palette.CYAN}


def test_held_and_alarm_reach_view_subscribers_only_when_they_flip():
    bench = Bench()
    views: list[FunnelView] = []
    bench.loop.subscribe_view(views.append)
    bench.tick(0.5)
    assert views == []
    bench.tick(1.0, shake=True)
    assert [v.held for v in views] == [True]
    bench.tick(3.0, shake=True)
    assert len(views) == 1, "no repeat while the state holds"
    bench.tick(3.0)  # still, then put down
    assert views[-1].held is False


def test_tipped_raises_the_alarm_fact_and_clearing_it_lowers_it():
    bench = Bench()
    views: list[FunnelView] = []
    bench.loop.subscribe_view(views.append)
    bench.tick(0.3, tipped_reading())
    assert views and views[-1].alarm is True
    bench.tick(3.0)
    assert views[-1].alarm is False


def test_muting_reaches_view_subscribers():
    loop, _ = _make_loop()
    views: list[FunnelView] = []
    loop.subscribe_view(views.append)
    loop.set_muted(True)
    loop.set_muted(True)
    assert [v.muted for v in views] == [True]


def test_a_fast_turn_replays_with_no_funnel_look_flash():
    loop, parts = _make_loop(
        wake_events=[WakeEvent(score=0.9)],
        stt_result=SttStreamResult(kind="final", text="hello"),
        turn_events=[
            TurnEvent(
                cue=Cue(phase=Phase.DONE, cue_seq=1),
                reply_text="hi",
                conversation_id="c",
                turn_id="t",
            )
        ],
    )
    assert loop.state.shown is FunnelState.IDLE
    eyes = FakeEyes()
    tap = LiveCaptureTap(parts["client"])
    director = EyesDirector(eyes, local_minutes=lambda: 12 * 60)  # midday, whatever the clock
    tap.subscribe(director.on_capture)
    loop.subscribe_view(director.on_view)
    loop._capture_scope = tap.sending_to_hub
    tap.start_recording()
    stop_event, thread = _start(loop)
    try:
        _wait_for(
            lambda: (
                loop.state.shown_trace[-1:]
                and loop.state.shown_trace[-1].state is (FunnelState.IDLE)
            ),
            timeout=3.0,
        )
        _wait_for(
            lambda: eyes.current_look is not None and eyes.current_look.colour is Palette.WHITE,
            timeout=3.0,
        )
    finally:
        _stop(stop_event, thread)
        director.close()
    looks_sent = [c for c in eyes.commands if c.kind == "set_look"]
    assert Palette.GREEN in {c.look.colour for c in looks_sent}, "the voice was sent: green"
    # looks_sent[0] is the director's initial paint at start-up, not a funnel change.
    for current, following in zip(looks_sent[1:], looks_sent[2:], strict=False):
        if current.look.colour in CUE_COLOURS or following.look.colour in CUE_COLOURS:
            continue  # a capture cue appears at once and holds its own floor
        assert following.t_s - current.t_s >= SETTLE_GATE_S - 0.05, (current, following)
