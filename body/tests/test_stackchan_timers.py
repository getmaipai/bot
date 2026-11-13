"""On-unit timers, host side: a fake unit that behaves like firmware patches 090 to 094."""

from __future__ import annotations

import json

import pytest

from maipai_body.bodies.stackchan.timers import (
    MAX_ACTIVE,
    TimerError,
    TimerService,
    clean_label,
    done_line,
)


class FakeUnit:
    """Answers the self.timer.* tools the way the firmware does (same caps, same error words)."""

    def __init__(self) -> None:
        self.rows: dict[int, dict] = {}
        self.next_id = 1
        self.calls: list[tuple[str, dict]] = []
        self.clock = True

    def __call__(self, name: str, arguments: dict) -> str:
        self.calls.append((name, dict(arguments)))
        if name == "self.timer.set":
            return self._add("timer", arguments["seconds"], arguments)
        if name == "self.timer.alarm":
            return self._add("alarm", 3600, arguments)
        if name == "self.timer.list":
            rows = [
                {"id": i, "kind": r["kind"], "left": r["left"], "label": r["label"]}
                for i, r in self.rows.items()
            ]
            return json.dumps({"clock": self.clock, "ringing": False, "timers": rows})
        if name == "self.timer.cancel":
            ident = arguments["id"]
            if ident == 0:
                found = bool(self.rows)
                self.rows.clear()
            else:
                found = self.rows.pop(ident, None) is not None
            return json.dumps({"ok": True} if found else {"ok": False, "error": "not_found"})
        if name == "self.timer.stop":
            return json.dumps({"ok": False, "error": "not_ringing"})
        if name == "self.timer.snooze":
            return self._add("timer", arguments["seconds"], {"label": "x"})
        raise AssertionError(name)

    def _add(self, kind: str, left: int, arguments: dict) -> str:
        if kind == "alarm" and not self.clock:
            return json.dumps({"ok": False, "error": "no_clock"})
        if len(self.rows) >= 8:
            return json.dumps({"ok": False, "error": "full"})
        ident = self.next_id
        self.next_id += 1
        self.rows[ident] = {"kind": kind, "left": left, "label": arguments.get("label", "")}
        return json.dumps({"ok": True, "id": ident})


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(**overrides):
    unit = FakeUnit()
    clock = Clock()
    said: list[str] = []
    state = {"busy": False}

    def say(text: str) -> bool:
        if state["busy"]:
            return False
        said.append(text)
        return True

    service = TimerService(unit, say=say, clock=clock, **overrides)
    return service, unit, clock, said, state


def test_set_timer_sends_clean_arguments_and_counts_it():
    service, unit, _clock, _said, _ = make()
    reply = service.set_timer(600, "Tea <b>time</b>")
    assert reply["ok"] and reply["id"] == 1 and reply["seconds"] == 600
    assert unit.calls[-1] == (
        "self.timer.set",
        {"seconds": 600, "label": "Tea btimeb", "silent": False},
    )
    assert service.active_count() == 1


def test_caps_are_checked_before_the_unit_is_asked():
    service, unit, *_ = make()
    with pytest.raises(TimerError, match="at most 24 hours"):
        service.set_timer(86401)
    with pytest.raises(TimerError, match="could not read that time"):
        service.set_timer(0)
    with pytest.raises(TimerError, match="could not read that time"):
        service.set_timer(True)
    assert unit.calls == []
    for _ in range(MAX_ACTIVE):
        service.set_timer(60)
    calls = len(unit.calls)
    with pytest.raises(TimerError, match="already have 8"):
        service.set_timer(60)
    assert len(unit.calls) == calls  # refused here, never sent


def test_alarm_needs_valid_time_and_the_unit_clock():
    service, unit, *_ = make()
    with pytest.raises(TimerError):
        service.set_alarm(24, 0)
    with pytest.raises(TimerError):
        service.set_alarm(7, 60)
    unit.clock = False
    with pytest.raises(TimerError, match="clock is not set"):
        service.set_alarm(7, 30, "wake up")
    unit.clock = True
    assert service.set_alarm(7, 30, "wake up")["kind"] == "alarm"


def test_disabled_refuses_new_timers_but_lists_and_cancels():
    service, unit, *_ = make()
    service.set_timer(60)
    service.apply_settings({"robot.timers.enabled": False})
    with pytest.raises(TimerError, match="turned off"):
        service.set_timer(60)
    with pytest.raises(TimerError, match="turned off"):
        service.set_alarm(7, 0)
    assert len(service.list_timers()["timers"]) == 1
    service.cancel(1)
    service.apply_settings({"robot.timers.enabled": True})
    service.set_timer(60)


def test_muted_unit_is_told_to_ring_silently():
    service, unit, *_ = make(muted=lambda: True)
    service.set_timer(30)
    assert unit.calls[-1][1]["silent"] is True


def test_list_replaces_the_count_and_cancel_all_empties_it():
    service, unit, *_ = make()
    assert service.active_count() is None  # not known until asked or set
    service.set_timer(30)
    service.set_timer(40)
    assert service.list_timers()["timers"][0]["id"] == 1
    assert service.active_count() == 2
    service.cancel(None)
    assert service.active_count() == 0
    with pytest.raises(TimerError, match="could not find"):
        service.cancel(99)
    service.forget()
    assert service.active_count() is None


def test_fired_timer_is_spoken_when_the_robot_is_free_and_not_repeated():
    service, _unit, clock, said, state = make()
    service.set_timer(30, "pasta")
    state["busy"] = True
    service.on_event("timer_fired", {"id": 1, "what": "timer", "label": "pasta", "late": 0})
    assert service.active_count() == 0
    service.tick()
    assert said == []  # busy: not spoken yet
    state["busy"] = False
    clock.now += 2
    service.tick()
    service.tick()
    assert said == ["Your pasta timer is done."]


def test_line_is_dropped_when_the_ring_ended_first_or_it_took_too_long():
    service, _unit, clock, said, state = make()
    service.on_event("timer_fired", {"id": 1, "what": "timer", "label": ""})
    service.on_event("timer_ended", {"id": 1, "how": "touch"})
    service.tick()
    assert said == []
    state["busy"] = True
    service.on_event("timer_fired", {"id": 2, "what": "alarm", "label": ""})
    clock.now += 31
    state["busy"] = False
    service.tick()
    assert said == []


def test_no_spoken_line_at_night_or_when_muted():
    for kwargs in ({"night": lambda: True}, {"muted": lambda: True}):
        service, _unit, _clock, said, _ = make(**kwargs)
        service.on_event("timer_fired", {"id": 1, "what": "timer", "label": "x"})
        service.tick()
        assert said == []


def test_alarm_line_and_label_cleaning():
    assert done_line("alarm", "") == "Your alarm is going off."
    assert done_line("alarm", "gym") == "Your gym alarm is going off."
    assert done_line("timer", "") == "Your timer is done."
    assert clean_label("a\nb  c" + "x" * 40) == ("a b c" + "x" * 40)[:24]
    assert clean_label(5) == ""


def test_hub_commands_answer_ok_or_a_plain_error_and_never_raise():
    service, unit, *_ = make()
    h = service.handlers()
    assert h["timer_set"]({"seconds": 90, "label": "eggs"})["ok"] is True
    assert h["alarm_set"]({"hour": 7, "minute": 15})["ok"] is True
    listed = h["timer_list"]({})
    assert listed["ok"] and len(listed["timers"]) == 2
    bad = h["timer_set"]({"seconds": "soon"})
    assert bad["ok"] is False and "could not read" in bad["error"]
    assert h["timer_cancel"]({"id": 1})["ok"] is True
    assert h["timer_cancel"]({})["ok"] is True  # no id: all of them
    assert h["timer_stop"]({})["ok"] is False  # nothing ringing: plain words
    assert "Nothing is ringing" in h["timer_stop"]({})["error"]
    assert h["timer_snooze"]({"seconds": 9999})["ok"] is False

    def lost(_name, _args):
        raise ConnectionError("no unit")

    away = TimerService(lost, clock=Clock())
    reply = away.handlers()["timer_set"]({"seconds": 5})
    assert reply["ok"] is False and "could not reach my body" in reply["error"]


def test_timer_events_pass_through_the_companion_with_their_fields():
    from maipai_body.bodies.stackchan.companion import StackChanCompanion

    rows = [
        {"kind": "timer_fired", "at_ms": 5, "id": 3, "label": "tea", "late": 0},
        {"kind": "timer_ended", "at_ms": 9, "id": 3, "how": "touch"},
    ]
    companion = StackChanCompanion(lambda _name, _args: rows)
    fired, ended = companion.poll_events()
    assert fired.kind == "timer_fired" and fired.extra["label"] == "tea" and fired.extra["id"] == 3
    assert ended.extra == {"id": 3, "how": "touch"}
