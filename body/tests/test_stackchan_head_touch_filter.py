"""Phantom head touches are dropped; a real stroke is kept (owner report 2026-10-21)."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from maipai_body.bodies.stackchan.head_touch_filter import HeadTouchFilter


def _ev(kind, **extra):
    return SimpleNamespace(kind=kind, extra=extra or None)


def test_a_lone_head_touch_is_ignored_and_other_events_pass():
    filt = HeadTouchFilter()
    kept = filt.accept(0.0, [_ev("head_touch"), _ev("shake")])
    assert [e.kind for e in kept] == ["shake"]


def test_a_burst_in_one_look_is_a_real_stroke():
    filt = HeadTouchFilter()
    kept = filt.accept(0.0, [_ev("head_touch"), _ev("head_swipe_forward")])
    assert [e.kind for e in kept] == ["head_touch", "head_swipe_forward"]


def test_a_repeat_within_a_few_seconds_is_real_but_a_phantom_every_ten_seconds_is_not():
    filt = HeadTouchFilter()
    assert filt.accept(0.0, [_ev("head_touch")]) == []
    assert len(filt.accept(2.0, [_ev("head_touch")])) == 1
    filt = HeadTouchFilter()
    for step in range(5):
        assert filt.accept(step * 10.0, [_ev("head_touch")]) == []


def test_a_contact_the_unit_says_was_held_is_real_at_once():
    filt = HeadTouchFilter()
    assert len(filt.accept(0.0, [_ev("head_touch", held_ms=650)])) == 1
    assert filt.accept(10.0, [_ev("head_touch", held_ms=80)]) == []


def test_one_info_line_a_minute_counts_what_was_ignored(caplog):
    filt = HeadTouchFilter()
    with caplog.at_level(logging.INFO, logger="maipai_body.bodies.stackchan.head_touch_filter"):
        for step in range(12):
            filt.accept(step * 10.0, [_ev("head_touch")])
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 2 and "ignored 1 lone head touch" in lines[0]


def test_a_phantom_does_not_wake_a_sleeping_robot():
    from maipai_body.app import StackChanBehavior
    from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
    from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient

    behavior = StackChanBehavior(StackChanRobotAdapter(FakeStackChanDeviceClient()).robot)
    try:
        behavior._rest._stage = "asleep"
        queue = [[], [_ev("head_touch")]]
        behavior.event_poll = lambda: queue.pop(0) if queue else []
        seen = []
        behavior.reaction = seen.append
        behavior.wake_on_touch(0.0)
        assert behavior.wake_on_touch(5.0) is False
        assert seen == []
    finally:
        behavior.close()


def test_a_swipe_the_unit_says_was_held_is_real_at_once():
    filt = HeadTouchFilter()
    assert len(filt.accept(0.0, [_ev("head_swipe_forward", held_ms=400)])) == 1


def test_companion_keeps_held_ms_on_head_events():
    from maipai_body.bodies.stackchan.companion import StackChanCompanion

    companion = StackChanCompanion(
        lambda name, args: [{"kind": "head_swipe_back", "at_ms": 3, "held_ms": 400}]
    )
    (event,) = companion.poll_events()
    assert event.extra == {"held_ms": 400}


def test_stop_word_hits_and_start_up_are_logged_with_the_fixed_command_name(caplog):
    from maipai_body.app import StackChanBehavior
    from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
    from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient

    behavior = StackChanBehavior(StackChanRobotAdapter(FakeStackChanDeviceClient()).robot)
    try:
        behavior._rest = type("Rest", (), {"stage": "awake"})()
        batch = [
            _ev("stop_word", state="ready", cost=3100),
            _ev("stop_word", cmd="stop", score=91, second=40, accepted=True),
            _ev("stop_word", cmd="quiet", score=62, second=10, accepted=False),
        ]
        queue = [[], batch]
        behavior.event_poll = lambda: queue.pop(0) if queue else []
        behavior.wake_on_touch(0.0)
        with caplog.at_level(logging.INFO, logger="maipai_body.app"):
            behavior.wake_on_touch(5.0)
        lines = [r.getMessage() for r in caplog.records]
        assert "unit stop word: stop_word state=ready cost=3100" in lines
        assert "unit stop word: heard 'stop', score 91, second 40 (accepted)" in lines
        assert "unit stop word: heard 'quiet', score 62, second 10 (rejected)" in lines
    finally:
        behavior.close()


def test_a_touch_the_unit_marks_strong_is_real_at_once():
    filt = HeadTouchFilter()
    assert len(filt.accept(0.0, [_ev("head_touch", strong=1)])) == 1
