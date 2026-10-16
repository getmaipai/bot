"""SLEEP-AUTO-01 feed: the presence tick drives the policy and the engine's sleep state."""

from __future__ import annotations

from maipai_body.presence.observations import PresenceObservation
from maipai_body.presence.sleep_auto import SleepAutoPolicy
from tests.test_run_loop import _make_loop


def _obs(*, face=False, speech=False):
    return PresenceObservation(
        t_received_ns=0, face_detected=face, face_x=0.0 if face else None, speech_detected=speech
    )


def _loop(**kwargs):
    state = {"luma": 5.0, "quiet": False, "now": 1000.0}
    loop, parts = _make_loop(
        sleep_auto=SleepAutoPolicy(),
        luma_source=lambda: state["luma"],
        quiet_hours=lambda: state["quiet"],
        sleep_clock=lambda: state["now"],
        **kwargs,
    )
    return loop, state


def _tick(loop, state, obs, seconds=0.5):
    state["now"] += seconds
    loop._sleep_tick(obs, held=False)


def test_ten_dark_quiet_minutes_put_the_robot_to_sleep_and_a_face_wakes_it():
    loop, state = _loop()
    _tick(loop, state, _obs())
    _tick(loop, state, _obs(), 599.0)
    assert getattr(loop._expression, "sleep_calls", []) == []
    _tick(loop, state, _obs(), 2.0)
    assert loop._expression.sleep_calls == [True]
    assert loop._is_asleep() is True
    _tick(loop, state, _obs(face=True))
    assert loop._expression.sleep_calls == [True, False]
    assert loop._is_asleep() is False


def test_light_alone_never_sleeps():
    loop, state = _loop()
    state["luma"] = 120.0
    for _ in range(5):
        _tick(loop, state, _obs(), 300.0)
    assert getattr(loop._expression, "sleep_calls", []) == []


def test_quiet_hours_sleep_even_in_the_light():
    loop, state = _loop()
    state["luma"] = 120.0
    state["quiet"] = True
    _tick(loop, state, _obs())
    assert loop._expression.sleep_calls == [True]


def test_a_knock_or_touch_wake_clears_the_auto_sleep_state():
    loop, state = _loop()
    state["quiet"] = True
    _tick(loop, state, _obs())
    loop._wake_from_sleep()
    assert loop._expression.sleep_calls == [True, False]
    assert loop._sleep_auto.asleep is False


def test_a_running_turn_and_a_carried_robot_are_not_slept():
    loop, state = _loop()
    state["quiet"] = True
    loop._sleep_tick(_obs(), held=True)
    assert getattr(loop._expression, "sleep_calls", []) == []
    from maipai_body.presence.funnel import FunnelState

    loop._enter(FunnelState.SPEAKING)
    _tick(loop, state, _obs())
    assert getattr(loop._expression, "sleep_calls", []) == []


def test_without_a_policy_nothing_changes():
    loop, _parts = _make_loop()
    loop._sleep_tick(_obs(), held=False)
    assert loop._is_asleep is None
