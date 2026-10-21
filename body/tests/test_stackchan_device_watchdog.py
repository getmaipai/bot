"""The watch on a unit that stays connected but stops answering."""

from __future__ import annotations

import logging

from maipai_body.bodies.stackchan.xiaozhi.watchdog import DeviceWatchdog


def _dog(now, reboots):
    return DeviceWatchdog(clock=lambda: now[0], reboot=lambda: reboots.append(now[0]))


def test_one_warning_with_both_ages_after_a_minute_of_failures(caplog):
    now, reboots = [1000.0], []
    dog = _dog(now, reboots)
    dog.note_message(audio=True)
    now[0] += 30
    dog.note_message(audio=False)
    with caplog.at_level(logging.WARNING):
        dog.note_tool(False)  # the first failure starts the clock
        for _ in range(7):
            now[0] += 10
            dog.note_tool(False)
    lines = [
        r.getMessage() for r in caplog.records if "has not answered tool calls" in r.getMessage()
    ]
    assert len(lines) == 1
    assert "last audio frame" in lines[0] and "last message from the unit" in lines[0]


def test_an_answer_resets_the_clock():
    now, reboots = [0.0], []
    dog = _dog(now, reboots)
    dog.note_tool(False)
    now[0] += 100
    dog.note_tool(True)
    now[0] += 100
    dog.note_tool(False)
    now[0] += 30
    dog.note_tool(False)
    assert reboots == []


def test_the_unit_is_asked_to_restart_after_two_minutes_and_not_more_than_every_ten():
    now, reboots = [0.0], []
    dog = _dog(now, reboots)
    dog.note_tool(False)
    for _ in range(40):
        now[0] += 5
        dog.note_tool(False)
    assert len(reboots) == 1  # at about 120 s, not again within ten minutes
    for _ in range(200):
        now[0] += 5
        dog.note_tool(False)
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
    dog.note_tool(False)
    now[0] += 130
    dog.note_tool(False)  # logs, never raises
