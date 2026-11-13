"""The watch on a unit that stays connected but stops answering (a sliding window, rung (b))."""

from __future__ import annotations

import logging

from maipai_body.bodies.stackchan.xiaozhi.watchdog import DeviceWatchdog


def _dog(now, reboots):
    return DeviceWatchdog(clock=lambda: now[0], reboot=lambda: reboots.append(now[0]))


def _feed(dog, now, outcomes, *, every=5.0):
    for ok in outcomes:
        now[0] += every
        dog.note_tool(ok)


def test_one_warning_with_both_ages_when_timeouts_outnumber_answers(caplog):
    now, reboots = [1000.0], []
    dog = _dog(now, reboots)
    dog.note_message(audio=True)
    now[0] += 30
    dog.note_message(audio=False)
    with caplog.at_level(logging.WARNING):
        _feed(dog, now, [True, False, False, False, False, False, False, False])
    lines = [
        r.getMessage() for r in caplog.records if "has not answered tool calls" in r.getMessage()
    ]
    assert len(lines) == 1
    assert "last audio frame" in lines[0] and "last message from the unit" in lines[0]
    assert "timed out" in lines[0]


def test_the_2026_11_12_freeze_is_caught_when_one_call_in_three_still_answers():
    # 23:40 case: 7 timeouts and 2 answers in 150 s; the old watch never started its clock.
    now, reboots = [0.0], []
    dog = _dog(now, reboots)
    pattern = [False, False, True] * 20
    _feed(dog, now, pattern, every=5.0)
    assert len(reboots) == 1
    assert 120 <= reboots[0] <= 200  # warned at about 30 s, restart 120 s after the warning


def test_a_healthy_mix_never_warns_or_restarts(caplog):
    now, reboots = [0.0], []
    dog = _dog(now, reboots)
    with caplog.at_level(logging.WARNING):
        _feed(dog, now, ([True] * 7 + [False]) * 40, every=3.0)
    assert reboots == []
    assert not [r for r in caplog.records if "has not answered" in r.getMessage()]


def test_no_answer_at_all_for_a_minute_asks_for_a_restart():
    now, reboots = [0.0], []
    dog = _dog(now, reboots)
    dog.note_tool(True)
    _feed(dog, now, [False] * 20, every=5.0)
    assert len(reboots) == 1
    assert 60 <= reboots[0] <= 75


def test_quiet_time_without_calls_is_not_a_failure():
    now, reboots = [0.0], []
    dog = _dog(now, reboots)
    dog.note_tool(True)
    now[0] += 3600
    dog.note_tool(False)
    assert reboots == []


def test_an_answer_run_clears_the_trouble():
    now, reboots = [0.0], []
    dog = _dog(now, reboots)
    _feed(dog, now, [False] * 8, every=5.0)  # warns, not yet 60 s without an answer
    _feed(dog, now, [True] * 30, every=5.0)
    _feed(dog, now, [False] * 3, every=5.0)
    assert reboots == []


def test_the_restart_is_asked_at_most_once_per_ten_minutes():
    now, reboots = [0.0], []
    dog = _dog(now, reboots)
    _feed(dog, now, [False] * 40, every=5.0)
    assert len(reboots) == 1
    _feed(dog, now, [False] * 80, every=5.0)  # 400 s more: 600 s after the first ask
    assert len(reboots) == 1
    _feed(dog, now, [False] * 40, every=5.0)
    assert len(reboots) == 2


def test_no_socket_means_nothing_to_warn_or_restart():
    now, reboots = [0.0], []
    dog = _dog(now, reboots)
    for _ in range(100):
        now[0] += 5
        dog.note_tool(False, socket_open=False)
    assert reboots == []


def test_a_failing_restart_request_does_not_raise():
    now = [0.0]

    def boom():
        raise OSError("socket gone")

    dog = DeviceWatchdog(clock=lambda: now[0], reboot=boom)
    dog.note_tool(True)
    _feed(dog, now, [False] * 20, every=5.0)  # logs, never raises
