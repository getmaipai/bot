"""OFFER-01: the robot's side of a hub offer, with a scripted spotter."""

from __future__ import annotations

import numpy as np
import pytest

from maipai_body.initiative.offer import WINDOW_S, OfferController, OfferGates

BLOCK = np.zeros(1280, dtype="f4")


class ScriptedEngine:
    """Returns the queued tag on the next accepted block."""

    def __init__(self) -> None:
        self.tags: list[str] = []
        self.begins = 0

    def begin(self) -> None:
        self.begins += 1

    def accept(self, block):
        return self.tags.pop(0) if self.tags else None

    def finish(self):
        return None


class Rig:
    def __init__(self, **flags) -> None:
        self.now = 100.0
        self.flags = {
            "busy": False,
            "muted": False,
            "held": False,
            "asleep": False,
            "outage": False,
            "guest_app": False,
            "attentive": True,
            "child": False,
            **flags,
        }
        self.engine = ScriptedEngine()
        self.rendered: list[str] = []
        self.frames: list[dict] = []
        self.turns: list[tuple[str, str, str]] = []
        self.spoken: list[str] = []
        self.blocks = 0
        f = self.flags
        self.controller = OfferController(
            engine=self.engine,
            poll_blocks=self._blocks,
            render=lambda p: self.rendered.append(p) or True,
            send_frame=lambda fr: self.frames.append(fr) or True,
            open_turn=lambda *a: self.turns.append(a),
            gates=OfferGates(
                busy=lambda: f["busy"],
                muted=lambda: f["muted"],
                held=lambda: f["held"],
                asleep=lambda: f["asleep"],
                outage=lambda: f["outage"],
                guest_app=lambda: f["guest_app"],
                attentive=lambda _p: f["attentive"],
                child_present=lambda: f["child"],
            ),
            speak=self.spoken.append,
            clock=lambda: self.now,
        )

    def _blocks(self):
        return [BLOCK] * self.blocks

    def offer(self, offer_id="of_1", person="usr_adult"):
        return self.controller.receive(
            {
                "offer_id": offer_id,
                "person_id": person,
                "tier": "ask",
                "non_personal_line": "Got a sec?",
            }
        )


def test_offer_renders_and_listens():
    rig = Rig()
    assert rig.offer() == {"offer": "queued"}
    assert rig.controller.service() is True
    assert rig.rendered == ["offer"]
    assert rig.spoken == ["Got a sec?"]


@pytest.mark.parametrize("phrase", ["go ahead", "yes please", "okay go ahead"])
def test_accept_phrase_opens_exactly_one_turn_with_the_offer_id(phrase):
    rig = Rig()
    rig.offer()
    rig.controller.service()
    rig.blocks = 1
    rig.engine.tags.append("@" + phrase.replace(" ", "_"))
    assert rig.controller.service() is False
    assert rig.turns == [(phrase, "of_1", "usr_adult")]
    rig.engine.tags.append("@go_ahead")
    assert rig.controller.service() is False
    assert len(rig.turns) == 1


def test_near_miss_never_accepts():
    rig = Rig()
    rig.offer()
    rig.controller.service()
    rig.blocks = 1
    for tag in ("@go_away", "@yes", "@okay", "@stop", "@go_a_head_now"):
        rig.engine.tags.append(tag)
        rig.controller.service()
    assert rig.turns == []
    assert rig.frames == []


def test_mid_turn_offer_is_deferred_not_rendered():
    rig = Rig(busy=True)
    assert rig.offer() == {"offer": "queued"}
    assert rig.controller.service() is False
    assert rig.rendered == []
    rig.flags["busy"] = False
    assert rig.controller.service() is True
    assert rig.rendered == ["offer"]


def test_deferred_offer_is_dropped_after_the_cap():
    rig = Rig(busy=True)
    rig.offer()
    rig.now += 121
    rig.flags["busy"] = False
    assert rig.controller.service() is False
    assert rig.rendered == []


def test_not_attentive_defers():
    rig = Rig(attentive=False)
    rig.offer()
    assert rig.controller.service() is False
    assert rig.rendered == []


@pytest.mark.parametrize(
    ("flag", "reason"),
    [
        ("muted", "muted"),
        ("held", "held"),
        ("asleep", "asleep"),
        ("outage", "outage"),
        ("guest_app", "guest_app"),
        ("child", "child_present"),
    ],
)
def test_gates_refuse_on_arrival(flag, reason):
    rig = Rig(**{flag: True})
    assert rig.offer() == {"offer": "refused", "reason": reason}
    assert rig.controller.service() is False
    assert rig.rendered == []


def test_no_spotter_refuses():
    rig = Rig()
    rig.controller._engine = None
    assert rig.offer() == {"offer": "refused", "reason": "no_spotter"}


def test_second_offer_while_one_is_open_is_refused():
    rig = Rig()
    rig.offer()
    assert rig.offer("of_2")["reason"] == "offer_in_progress"


def test_not_now_sends_a_snooze_frame():
    rig = Rig()
    rig.offer()
    rig.controller.service()
    rig.blocks = 1
    rig.engine.tags.append("@not_now")
    assert rig.controller.service() is False
    assert rig.frames == [
        {"kind": "offer_snooze", "payload": {"offer_id": "of_1", "source": "voice"}}
    ]
    assert rig.turns == []
    assert rig.rendered[-1] == "settle"


def test_no_thanks_sends_a_declining_answer():
    rig = Rig()
    rig.offer()
    rig.controller.service()
    rig.blocks = 1
    rig.engine.tags.append("@no_thanks")
    rig.controller.service()
    assert rig.frames == [
        {
            "kind": "offer_answer",
            "payload": {"offer_id": "of_1", "approved": False, "source": "voice"},
        }
    ]


def test_window_reoffers_once_then_settles_at_ten_seconds_and_sends_nothing():
    rig = Rig()
    rig.offer()
    rig.controller.service()
    rig.now += 5.1
    assert rig.controller.service() is True
    rig.now += 1
    assert rig.controller.service() is True
    assert rig.rendered == ["offer", "offer"]
    rig.now += WINDOW_S
    assert rig.controller.service() is False
    assert rig.rendered == ["offer", "offer", "settle"]
    assert rig.frames == []
    assert rig.turns == []
    assert rig.controller.service() is False


def test_accept_by_someone_else_is_ignored():
    rig = Rig()
    rig.offer()
    rig.controller.service()
    rig.flags["attentive"] = False
    rig.blocks = 1
    rig.engine.tags.append("@go_ahead")
    assert rig.controller.service() is True
    assert rig.turns == []


def test_mute_during_the_window_ends_it_quietly():
    rig = Rig()
    rig.offer()
    rig.controller.service()
    rig.flags["muted"] = True
    assert rig.controller.service() is False
    assert rig.turns == [] and rig.frames == []


def test_gestures_and_touch_have_no_path_to_accept():
    """The controller exposes no gesture or touch input at all."""
    rig = Rig()
    names = {n for n in dir(rig.controller) if not n.startswith("_")}
    assert names == {"receive", "service"}


def test_the_window_callback_tells_the_eyes_when_it_opens_and_closes():
    rig = Rig()
    seen: list[bool] = []
    rig.controller._on_window = seen.append
    rig.offer()
    rig.controller.service()
    assert seen == [True]
    rig.now += WINDOW_S + 1
    rig.controller.service()
    assert seen == [True, False]
