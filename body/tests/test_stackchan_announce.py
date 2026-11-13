"""Hub announcements: the gates and the delivery, with a fake clock and a fake unit."""

from __future__ import annotations

from maipai_body.bodies.stackchan.announce import TEXT_MAX, Announcer, clean_text


def make(night=False):
    shown: list[str] = []
    said: list[str] = []
    state = {"busy": False, "night": night, "now": 0.0, "show_fails": False}

    def show(text: str) -> object:
        if state["show_fails"]:
            raise ConnectionError("no unit")
        shown.append(text)
        return True

    def say(text: str) -> bool:
        if state["busy"]:
            return False
        said.append(text)
        return True

    announcer = Announcer(
        show=show, say=say, night=lambda: state["night"], clock=lambda: state["now"]
    )
    return announcer, shown, said, state


def test_delivers_the_card_then_says_the_line():
    announcer, shown, said, _ = make()
    assert announcer.handle({"text": "Dinner is ready"}) == {"status": "delivered"}
    assert shown == ["Dinner is ready"] and said == []
    announcer.tick()
    announcer.tick()
    assert said == ["Dinner is ready"]  # once


def test_waits_while_a_turn_is_busy_then_gives_up():
    announcer, _shown, said, state = make()
    state["busy"] = True
    announcer.handle({"text": "Time to go"})
    announcer.tick()
    state["now"] = 13
    announcer.tick()
    state["busy"] = False
    announcer.tick()
    assert said == []  # too late: the moment passed


def test_night_refuses_unless_urgent():
    announcer, shown, said, state = make(night=True)
    assert announcer.handle({"text": "Dinner is ready"}) == {"status": "refused", "reason": "night"}
    assert announcer.handle({"text": "Smoke alarm", "urgent": True}) == {"status": "delivered"}
    assert shown == ["Smoke alarm"]
    announcer.tick()
    assert said == ["Smoke alarm"]


def test_muted_and_quiet_refuse_even_urgent_and_disabled_refuses_all():
    announcer, shown, *_ = make()
    announcer.apply_settings({"robot.muted": True})
    assert announcer.handle({"text": "hi", "urgent": True})["reason"] == "muted"
    announcer.apply_settings({"robot.muted": False, "robot.quiet": True})
    assert announcer.handle({"text": "hi", "urgent": True})["reason"] == "quiet"
    announcer.apply_settings({"robot.quiet": False, "robot.announce.enabled": False})
    assert announcer.handle({"text": "hi"})["reason"] == "disabled"
    announcer.apply_settings({"robot.announce.enabled": True})
    assert announcer.handle({"text": "hi"})["status"] == "delivered"
    assert shown == ["hi"]


def test_absent_or_odd_flags_mean_off():
    announcer, *_ = make()
    announcer.apply_settings({})
    announcer.apply_settings({"robot.muted": "yes", "robot.quiet": 1})
    assert announcer.handle({"text": "hi"})["status"] == "delivered"


def test_empty_and_long_text():
    announcer, *_ = make()
    refused = announcer.handle({"text": "  \n "})
    assert refused["status"] == "refused" and "had no words" in refused["error"]
    assert announcer.handle({})["reason"] == "empty"
    long = ("word " * 80).strip()
    cleaned = clean_text(long)
    assert len(cleaned) <= TEXT_MAX and not cleaned.endswith(" ") and cleaned.endswith("word")
    assert clean_text("a\x07b\n\tc") == "a b c"
    assert clean_text(None) == ""


def test_unreachable_unit_is_refused_with_a_plain_error_and_nothing_is_said():
    announcer, _shown, said, state = make()
    state["show_fails"] = True
    reply = announcer.handle({"text": "Dinner"})
    assert reply["status"] == "refused" and reply["reason"] == "unreachable"
    assert "Check that it is on" in reply["error"]
    announcer.tick()
    assert said == []
