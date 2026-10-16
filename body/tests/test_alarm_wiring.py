"""ALARM-PLAY-01: the loop, expression, channel and clip hooks the alarm uses."""

from __future__ import annotations

import json

from maipai_body.expression.suppression import SuppressionContext, suppression_reason
from maipai_body.initiative.alarm import AlarmController
from maipai_body.link.channel import CommandChannel
from maipai_body.speech.offline_clips import (
    ALARM_GENERIC,
    Clip,
    Manifest,
    Voice,
    alarm_child_clip_ids,
    alarm_clip_ids,
)
from maipai_body.speech.wake import WakeEvent
from tests.test_run_loop import _make_loop, _start, _stop, _wait_for


def test_a_safety_alarm_shows_the_amber_fact_and_holds_the_pose_through_mute():
    loop, parts = _make_loop()
    loop.set_muted(True)
    loop.set_safety_alarm(True)
    assert loop.view().alarm is True
    assert parts["engine"].alarm_calls == [True]
    assert parts["playback"].stop_calls >= 1
    loop.set_safety_alarm(True)  # an edge, not a level
    assert parts["engine"].alarm_calls == [True]
    loop.set_safety_alarm(False)
    assert loop.view().alarm is False
    assert parts["engine"].alarm_calls == [True, False]


def test_a_wake_is_ignored_while_an_alarm_is_live_and_resumes_after():
    loop, parts = _make_loop(wake_events=[WakeEvent(score=0.9)])
    loop.set_safety_alarm(True)
    stop, thread = _start(loop)
    try:
        import time

        time.sleep(0.3)
        assert parts["stt"].call_count == 0
        assert parts["wake"].poll_count == 0  # not even scored
        loop.set_safety_alarm(False)
        _wait_for(lambda: parts["stt"].call_count >= 1)
    finally:
        _stop(stop, thread)


class _Detector:
    def __init__(self) -> None:
        self.resets = 0

    def accept(self, _block) -> bool:
        return True

    def reset(self) -> None:
        self.resets += 1


def test_a_spotted_stop_word_during_an_alarm_reaches_the_handler():
    heard: list[str] = []
    loop, _parts = _make_loop(stop_detector=_Detector())
    loop.set_alarm_word_handler(lambda word: heard.append(word) or True)
    loop.set_safety_alarm(True)
    stop, thread = _start(loop)
    try:
        _wait_for(lambda: bool(heard))
    finally:
        _stop(stop, thread)
    assert heard[0] == "stop"


def test_the_alarm_suppresses_every_cue_but_stop():
    context = SuppressionContext(alarm=True)
    assert suppression_reason("nod", context) == "alarm"
    assert suppression_reason("breathe", context) == "alarm"
    assert suppression_reason("stop", context) is None
    assert suppression_reason("nod", SuppressionContext()) is None


def test_the_alarm_pose_renders_through_mute_and_sleep_and_settles_after():
    loop, parts = _make_loop()
    loop.set_muted(True)
    loop.set_safety_alarm(True)
    assert parts["engine"]._engine._alarmed is True
    loop.set_safety_alarm(False)
    assert parts["engine"]._engine._alarmed is False


# -- the channel ------------------------------------------------------------


class _Ws:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


def test_the_channel_sends_only_while_connected_and_dispatches_alarm_commands():
    seen: list[dict] = []
    channel = CommandChannel("http://hub.example.com", "cookie", handlers={"alarm": seen.append})
    assert channel.send_frame({"type": "alarm_action"}) is False
    ws = _Ws()
    channel._ws = ws
    assert channel.send_frame({"type": "alarm_action", "alarm_id": "a1"}) is True
    assert ws.sent == [{"type": "alarm_action", "alarm_id": "a1"}]
    channel._handle_text(
        json.dumps(
            {
                "type": "device-command",
                "id": "e1",
                "kind": "alarm",
                "payload": {"alarm_id": "a1", "state": "active"},
            }
        ),
        ws,
    )
    assert seen == [{"alarm_id": "a1", "state": "active"}]
    assert {"type": "ack", "id": "e1"} in ws.sent


# -- the clips --------------------------------------------------------------


def _manifest(*clips):
    voice = Voice(engine="e", name="n", licence_checked=True)
    return Manifest(
        voice=voice,
        sample_rate=16000,
        clips=tuple(Clip(id=i, text=t, file=f"{i}.wav", sha256="x") for i, t in clips),
    )


def test_the_area_clip_is_chosen_by_kind_and_area_text_else_generic_else_none():
    manifest = _manifest(
        (ALARM_GENERIC, "A home alarm is on."),
        ("alarm-smoke-aaaaaaaaaaaa", "Smoke alarm in the kitchen."),
        ("alarm-gas-bbbbbbbbbbbb", "Gas alarm in the garage."),
    )
    have = {c.id for c in manifest.clips}.__contains__
    assert alarm_clip_ids(manifest, have, "smoke", "Kitchen") == ["alarm-smoke-aaaaaaaaaaaa"]
    assert alarm_clip_ids(manifest, have, "smoke", "garage") == [ALARM_GENERIC]
    assert alarm_clip_ids(manifest, have, None, None) == [ALARM_GENERIC]
    assert alarm_clip_ids(manifest, lambda _c: False, "smoke", "kitchen") == []
    assert alarm_child_clip_ids(have) == []  # Home makes no child line yet


def test_controller_and_loop_agree_end_to_end_on_fakes():
    loop, parts = _make_loop()
    events: list = []

    class Player:
        def chime(self):
            events.append("chime")

        def clips(self, ids):
            events.append(tuple(ids))
            return True

        def stop(self):
            events.append("stop")

    sent: list[dict] = []
    controller = AlarmController(
        player=Player(),
        present=loop.set_safety_alarm,
        resolve_clips=lambda _k, _a: [ALARM_GENERIC],
        child_clips=list,
        send_action=lambda m: sent.append(m) or True,
        audience=lambda: loop.speaker_snapshot()[1],
        is_child=lambda _e: False,
        evidence=lambda: loop.speaker_snapshot()[0],
    )
    controller.handle_command({"alarm_id": "a9", "state": "active", "kind": "smoke", "area": None})
    assert loop.view().alarm and parts["engine"].alarm_calls == [True]
    assert controller.on_spoken("stop")
    assert sent[0]["speaker_evidence"] == {"person": None, "basis": "unknown", "level": "unknown"}
    assert loop.view().alarm  # still live: only the hub's state ends it
    controller.handle_command({"alarm_id": "a9", "state": "cleared"})
    assert not loop.view().alarm and events[-1] == "stop"
